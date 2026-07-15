# Design Notes — `WORKFLOW_v2` (the polished workflow document)

This file records the framework decision and the styling / readability guidelines
applied when building the upgraded workflow document (`WORKFLOW_v2.html` and
`WORKFLOW_v2.pdf` at the repo root, produced by `tools/build_workflow_v2.py`).

## 1. Framework decision

**Chosen: HTML + CSS, rendered to PDF with Playwright (headless Chromium).**

The build emits a single **self-contained HTML file** (all CSS and diagrams are
inline; fonts come from Google Fonts with a robust system fallback) and then
prints it to **PDF** through Chromium's print engine.

### Why this, vs. the alternatives I researched

| Candidate | Verdict for this job |
|---|---|
| **HTML + CSS → PDF (Playwright)** ✅ chosen | Produces **two** shareable artifacts from one source (a styled HTML anyone can open in a browser, *and* a PDF). Full, pixel-level design control (CSS grid, gradients, custom callouts, inline SVG diagrams). Chromium's print pipeline is the most faithful HTML→PDF renderer. Installs cleanly on Windows via `pip install playwright` + `playwright install chromium` (no native system libraries). |
| **Typst** | Genuinely excellent: a modern, Rust-based typesetting engine — fast, deterministic, gorgeous typography, installable via `pip install typst`. Strongest *pure-PDF* option. Rejected only because it can't also emit a shareable **HTML** artifact, and reusing/“drawing” the diagrams (cetz) often needs network access to fetch packages. Best runner-up. |
| **Quarto** | A great wrapper around Typst/LaTeX/Pandoc, but it's aimed at computational notebooks; heavier install and more than we need for a single hand-tuned document. |
| **LaTeX** | Beautiful output, but brutal boilerplate and a large TeX install; overkill and slow to iterate for a design-led one-pager-style doc. |
| **WeasyPrint** | "Just use CSS" is appealing, but on **Windows** it needs the GTK/Pango/Cairo native stack, which is fragile to install. It also lacks modern CSS and scales poorly on long docs. Kept only as a documented fallback. |
| **wkhtmltopdf** | Effectively unmaintained; uses an ancient WebKit; poor modern-CSS support. |
| **Enhanced python-docx** | This is what the *existing* `WORKFLOW.docx` already uses. Great for `.docx`, but Word is not the most *shareable/beautiful* target and gives less layout control than CSS. We intentionally left it untouched and complemented it.|

**Reproducibility & safety:** the build script and all assets live under `tools/`.
The new artifacts are written as `WORKFLOW_v2.*` so the existing `WORKFLOW.md` and
`WORKFLOW.docx` are never overwritten.

## 2. Styling & readability guidelines applied

Grounded in the typography/technical-writing sources reviewed (typographic
hierarchy, WCAG contrast, atomic sections, stable callouts, plain language):

**Typography & hierarchy**
- **Two-family pairing only:** a display serif (`Fraunces`, with optical sizing)
  for headings + a humanist sans (`Inter`) for body, plus `JetBrains Mono` for code.
- Clear type scale and an **8px vertical-rhythm** spacing system; generous line
  height (1.6) on body copy for comfortable reading.
- Semantic heading levels (H1→H3); each stage is a short, **atomic** block.

**Colour, contrast, accessibility**
- A restrained finance **teal/green palette** (carried over from the `.docx` for
  brand continuity) with a warm gold accent.
- **Colour is semantic, not decorative:** blue = "in plain English", mint =
  analogy, gold/sand = caution/decision, green = tip/positive.
- Body text targets WCAG-AA contrast on light backgrounds; diagrams also carry
  text labels (not colour-only meaning).

**Making heavy terms digestible (progressive disclosure)**
- An **ELI5 hero** up top sets one analogy before any jargon appears.
- **"In plain English" boxes** sit right next to every technical passage.
- A **visual glossary** of cards (icon + term + plain meaning + mini-analogy).
- The 9 stages use **big numbered steps** with a one-line "what it really means".
- **Callout/admonition boxes** are used consistently and sparingly.

**Layout**
- Cover page with a gradient masthead; auto-generated, page-numbered PDF.
- White content cards on a soft tinted page; whitespace-led grid; two custom
  **inline-SVG diagrams** (architecture + the 9-stage flow) that stay crisp at any zoom.

## 3. How to re-build

```powershell
# one-time, from repo root:
python -m pip install playwright
python -m playwright install chromium

# build (writes WORKFLOW_v2.html and WORKFLOW_v2.pdf at the repo root):
python tools/build_workflow_v2.py
```

If Playwright/Chromium is unavailable, the script still writes the
self-contained `WORKFLOW_v2.html` (which prints cleanly to PDF from any browser),
and prints a notice instead of failing.
