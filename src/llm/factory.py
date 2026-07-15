"""LLM provider factory.

Returns a `complete(prompt, system=None) -> str` callable for the configured
provider (openai / anthropic / ollama). All providers are optional - if the
SDK or the network is unavailable we return a deterministic stub so the
pipeline still runs end-to-end (with degraded LLM-flavored output).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Protocol


class LLM(Protocol):
    def complete(self, prompt: str, system: str | None = None) -> str: ...

    # Optional capability: providers that support native structured output
    # implement complete_json. Others fall back to generic text + parse_json.
    def complete_json(  # type: ignore[empty-body]
        self, prompt: str, system: str | None = None, schema: dict | None = None
    ) -> str: ...


@dataclass
class _Stub:
    """Deterministic offline stub - used when no LLM is configured/reachable.

    Returns a short, structured-looking string so downstream JSON parsing has
    a chance, but flagged so the report can show a "LLM unavailable" notice.
    """

    name: str = "stub"

    def complete(self, prompt: str, system: str | None = None) -> str:
        # Return an empty JSON object - analysts have a fallback that
        # synthesizes a signal from deterministic factor scores when the LLM
        # output is empty or unparseable.
        return "{}"

    def complete_json(
        self, prompt: str, system: str | None = None, schema: dict | None = None
    ) -> str:
        return "{}"


def _make_openai(model: str, temperature: float) -> LLM | None:
    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    client = OpenAI(api_key=api_key)

    class _OpenAI:
        def complete(self, prompt: str, system: str | None = None) -> str:
            try:
                msgs: list[dict[str, Any]] = []
                if system:
                    msgs.append({"role": "system", "content": system})
                msgs.append({"role": "user", "content": prompt})
                resp = client.chat.completions.create(
                    model=model, temperature=temperature, messages=msgs
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception:
                return ""

        def complete_json(
            self, prompt: str, system: str | None = None, schema: dict | None = None
        ) -> str:
            try:
                msgs: list[dict[str, Any]] = []
                if system:
                    msgs.append({"role": "system", "content": system})
                msgs.append({"role": "user", "content": prompt})
                kwargs: dict[str, Any] = dict(
                    model=model, temperature=temperature, messages=msgs
                )
                if schema:
                    # Try strict json_schema first; fall back to plain json mode.
                    try:
                        kwargs["response_format"] = {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "result",
                                "schema": schema,
                                "strict": False,
                            },
                        }
                        resp = client.chat.completions.create(**kwargs)
                        return (resp.choices[0].message.content or "").strip()
                    except Exception:
                        kwargs["response_format"] = {"type": "json_object"}
                else:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = client.chat.completions.create(**kwargs)
                return (resp.choices[0].message.content or "").strip()
            except Exception:
                return ""

    return _OpenAI()


def _make_anthropic(model: str, temperature: float) -> LLM | None:
    try:
        import anthropic  # type: ignore
    except Exception:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    client = anthropic.Anthropic(api_key=api_key)

    class _Anthropic:
        def complete(self, prompt: str, system: str | None = None) -> str:
            try:
                resp = client.messages.create(
                    model=model,
                    max_tokens=1024,
                    temperature=temperature,
                    system=system or "",
                    messages=[{"role": "user", "content": prompt}],
                )
                return "".join(
                    block.text for block in resp.content if hasattr(block, "text")
                ).strip()
            except Exception:
                return ""

        def complete_json(
            self, prompt: str, system: str | None = None, schema: dict | None = None
        ) -> str:
            # Anthropic doesn't have a strict-json flag; emulate via tool use
            # when a schema is provided.
            if not schema:
                return self.complete(prompt, system)
            try:
                tool = {
                    "name": "submit",
                    "description": "Submit the structured answer.",
                    "input_schema": schema,
                }
                resp = client.messages.create(
                    model=model,
                    max_tokens=1024,
                    temperature=temperature,
                    system=system or "",
                    tools=[tool],
                    tool_choice={"type": "tool", "name": "submit"},
                    messages=[{"role": "user", "content": prompt}],
                )
                for block in resp.content:
                    if getattr(block, "type", "") == "tool_use":
                        return json.dumps(getattr(block, "input", {}) or {})
                return self.complete(prompt, system)
            except Exception:
                return ""

    return _Anthropic()


def _make_ollama(model: str, temperature: float) -> LLM | None:
    try:
        import requests  # type: ignore
    except Exception:
        return None
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        req_timeout = float(os.environ.get("OLLAMA_TIMEOUT", "120"))
    except ValueError:
        req_timeout = 120.0

    class _Ollama:
        def complete(self, prompt: str, system: str | None = None) -> str:
            try:
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "system": system or "",
                    "stream": False,
                    "options": {"temperature": temperature},
                }
                r = requests.post(
                    f"{host}/api/generate", json=payload, timeout=req_timeout
                )
                if r.status_code != 200:
                    return ""
                return (r.json().get("response") or "").strip()
            except Exception:
                return ""

        def complete_json(
            self, prompt: str, system: str | None = None, schema: dict | None = None
        ) -> str:
            try:
                payload: dict[str, Any] = {
                    "model": model,
                    "prompt": prompt,
                    "system": system or "",
                    "stream": False,
                    "format": schema if schema else "json",
                    "options": {"temperature": temperature},
                }
                r = requests.post(
                    f"{host}/api/generate", json=payload, timeout=req_timeout
                )
                if r.status_code != 200:
                    return ""
                return (r.json().get("response") or "").strip()
            except Exception:
                return ""

    return _Ollama()


def _make_cursor_io() -> LLM:
    """File-IO provider: dumps each prompt to a directory and reads a
    pre-authored JSON response from the matching file (looked up by SHA-256).

    Designed for two-pass workflows where the agent (e.g. running inside
    Cursor) wants to use the current chat's LLM as the analyst:

      1. First pass: directory has no response files. Each LLM call writes
         `<dir>/prompts/<sha>.txt` and returns "" -> agents fall back to
         their deterministic heuristics. This produces the *list of prompts*
         the human/Cursor LLM should answer.
      2. Human (or the Cursor chat LLM) writes a `<dir>/responses/<sha>.json`
         file for each prompt with valid JSON matching the requested schema.
      3. Second pass: the provider reads from `responses/`. If a response is
         missing it falls through to "" again, so partial coverage degrades
         gracefully.

    Configure via:
      LLM_PROVIDER=cursor_io
      CURSOR_LLM_DIR=./llm_cache  (default)
    """
    import hashlib
    from pathlib import Path

    base = Path(os.environ.get("CURSOR_LLM_DIR", "./llm_cache")).resolve()
    prompts_dir = base / "prompts"
    responses_dir = base / "responses"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    responses_dir.mkdir(parents=True, exist_ok=True)

    import re as _re

    def _normalise_for_hash(prompt: str) -> str:
        """Strip iterative debate text from bull/bear/manager prompts so they
        hash stably regardless of what earlier rounds emitted. Other prompts
        pass through untouched.
        """
        out = prompt
        if "PRIOR DEBATE:" in out and "\nDATA:" in out:
            out = _re.sub(
                r"PRIOR DEBATE:\n.*?\n\nDATA:",
                "PRIOR DEBATE:\n<NORMALISED>\n\nDATA:",
                out,
                flags=_re.DOTALL,
            )
        if "\n\nDEBATE:\n" in out:
            out = _re.sub(
                r"\n\nDEBATE:\n.*\Z",
                "\n\nDEBATE:\n<NORMALISED>",
                out,
                flags=_re.DOTALL,
            )
        return out

    def _hash(prompt: str, system: str | None) -> str:
        h = hashlib.sha256()
        h.update((system or "").encode("utf-8"))
        h.update(b"\n---SYSTEM_END---\n")
        h.update(_normalise_for_hash(prompt or "").encode("utf-8"))
        return h.hexdigest()[:16]

    class _CursorIO:
        def complete(self, prompt: str, system: str | None = None) -> str:
            sha = _hash(prompt, system)
            resp_path = responses_dir / f"{sha}.json"
            if resp_path.exists():
                try:
                    raw = resp_path.read_bytes()
                    # Best-effort decode: tolerate UTF-16 LE/BE (with or without
                    # BOM) which happens when files are written from PowerShell
                    # or some IDE tools.
                    if len(raw) >= 2 and raw[0:2] == b"\xff\xfe":
                        text = raw.decode("utf-16-le", errors="replace")
                    elif len(raw) >= 2 and raw[0:2] == b"\xfe\xff":
                        text = raw.decode("utf-16-be", errors="replace")
                    elif len(raw) >= 4 and raw[1] == 0 and raw[3] == 0:
                        text = raw.decode("utf-16-le", errors="replace")
                    elif len(raw) >= 4 and raw[0] == 0 and raw[2] == 0:
                        text = raw.decode("utf-16-be", errors="replace")
                    elif len(raw) >= 3 and raw[0:3] == b"\xef\xbb\xbf":
                        text = raw[3:].decode("utf-8", errors="replace")
                    else:
                        text = raw.decode("utf-8", errors="replace")
                    return text.strip()
                except OSError:
                    pass
            # Persist the unanswered prompt so the operator can answer it.
            prompt_path = prompts_dir / f"{sha}.txt"
            if not prompt_path.exists():
                try:
                    prompt_path.write_text(
                        (system or "(no system)")
                        + "\n\n========== PROMPT ==========\n\n"
                        + (prompt or ""),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
            return ""

        def complete_json(
            self, prompt: str, system: str | None = None, schema: dict | None = None
        ) -> str:
            return self.complete(prompt, system=system)

    return _CursorIO()


def get_llm() -> LLM:
    provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
    model = os.environ.get("LLM_MODEL", "llama3.1:8b")
    try:
        temperature = float(os.environ.get("LLM_TEMPERATURE", "0"))
    except ValueError:
        temperature = 0.0

    llm: LLM | None = None
    if provider == "openai":
        llm = _make_openai(model, temperature)
    elif provider == "anthropic":
        llm = _make_anthropic(model, temperature)
    elif provider == "ollama":
        llm = _make_ollama(model, temperature)
    elif provider == "cursor_io":
        llm = _make_cursor_io()

    return llm or _Stub()


# ---------------------------------------------------------------------------
# JSON helpers - LLMs occasionally wrap JSON in prose / code fences.
# ---------------------------------------------------------------------------


def parse_json(text: str) -> dict | list | None:
    """Best-effort JSON parsing of LLM output."""
    if not text:
        return None
    text = text.strip()
    # Strip ```json ... ``` fences.
    if text.startswith("```"):
        # remove first fence line and trailing fence
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # try first { ... } slice
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


def is_stub(llm: LLM) -> bool:
    return isinstance(llm, _Stub)


# ---------------------------------------------------------------------------
# Structured output with Pydantic validation + retry.
# ---------------------------------------------------------------------------


def complete_validated(
    llm: LLM,
    prompt: str,
    *,
    system: str | None,
    pydantic_model,
    json_schema: dict | None = None,
    retries: int = 1,
):
    """Call the LLM in JSON mode and validate against a pydantic model.

    On `ValidationError` we re-prompt once with the validation error attached
    so the model has a concrete shot at fixing its output. If validation
    still fails (or the LLM is the stub) we return None and let callers
    fall back to deterministic synthesis.
    """
    last_err: Exception | None = None
    last_text: str = ""
    for attempt in range(retries + 1):
        try:
            text = (
                llm.complete_json(prompt, system=system, schema=json_schema)
                if hasattr(llm, "complete_json")
                else llm.complete(prompt, system=system)
            )
        except Exception as e:
            last_err = e
            text = ""
        last_text = text or ""
        parsed = parse_json(text or "") or {}
        try:
            return pydantic_model.model_validate(parsed)
        except Exception as e:
            last_err = e
            if attempt < retries:
                prompt = (
                    prompt
                    + "\n\nThe previous response did not validate against the "
                    "required schema with this error: "
                    + str(e)[:600]
                    + "\nReturn ONLY a valid JSON object that matches the schema."
                )
                continue
    # Surface what we got for debugging without crashing.
    if last_err is not None:
        try:
            import logging

            logging.getLogger("finance_research_agent").debug(
                "complete_validated failed: %s; raw=%r", last_err, last_text[:500]
            )
        except Exception:
            pass
    return None


def grade_rationale(rationale: str, metric_values: dict[str, Any]) -> float:
    """Heuristic 'self-check' on rationale quality.

    Returns a multiplier in (0, 1] that the caller should apply to the LLM's
    self-reported confidence. We require the rationale to mention at least
    one *concrete number* that appears in the supplied metric_values; this
    catches the most common LLM failure mode where the model writes generic
    prose without grounding it in the data.
    """
    if not rationale:
        return 0.5
    # Has at least one number.
    has_digit = any(c.isdigit() for c in rationale)
    if not has_digit:
        return 0.5
    # Bonus if any metric value (rounded loosely) appears as a substring.
    text = rationale.lower()
    grounded = False
    for v in metric_values.values():
        if v is None or not isinstance(v, (int, float)):
            continue
        for needle in (f"{v:.0f}", f"{v:.1f}", f"{v:.2f}", f"{v*100:.0f}"):
            if needle.lstrip("-") in text:
                grounded = True
                break
        if grounded:
            break
    return 1.0 if grounded else 0.75
