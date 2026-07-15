"""
Prompt Builders - All LLM prompt generation functions.

Extracted from geminiQCWithScript, geminiTranslationQC, and llmTranslationHelper
to reduce file sizes and centralize prompt logic.

Each function is prefixed by its source pipeline when names would collide:
  - generate_qc_*      -> from geminiQCWithScript (transcription QC)
  - generate_llm_*     -> from llmTranslationHelper (LLM translation)
  - generate_master_*  -> from geminiTranslationQC (translation QC / AIQC)
  - generate_character_* -> from geminiTranslationQC
"""

import json
import os
import logging

from HelperClasses.geminiTranslation.gemini_client import (
    calling_gemini as callingGemini,
    create_vertexai_client as _create_vertexai_client,
)

logger = logging.getLogger(__name__)


# ======================================================================
# Transcription QC prompts (from geminiQCWithScript)
# ======================================================================

def generate_qc_translation_prompt_old(batches_data, input_language, output_language):
    """
    Builds a translation prompt for subtitles (legacy, no script context).

    Purpose:
        Produces a prompt for translating subtitle batches between languages with holistic
        understanding and sentence-level segmentation. Does not include script context.

    Args:
        batches_data: list — Batch of subtitle dicts (e.g., with "transcripts" key).
        input_language: str — Source language of the subtitles.
        output_language: str — Target language for translation.

    Returns:
        str: The full prompt string for the LLM.

    Side effects / Errors:
        None. Converts batches_data to JSON internally.
    """
    batches_data = json.dumps(batches_data)

    arabic_rule = ""
    if output_language.lower() == "arabic":
        arabic_rule = "\n\n        🔸 **Arabic Dialect Restriction:** When translating to Arabic, you MUST use Modern Standard Arabic (MSA) only. Do NOT use Saudi dialect, Egyptian dialect, or any other regional dialect. All translations must be in standard Arabic dialect that is universally understood across all Arabic-speaking regions. All numbers must be written using standard English digits (1, 2, 3) — not Arabic-Indic digits (١، ٢، ٣)."

    default_prompt = f"""
    You are a highly skilled and meticulous subtitle translator with expertise in translating between various languages while maintaining accuracy, cultural nuance, and natural-sounding dialogue. You meticulously adhere to established subtitle guidelines and best practices and prioritize understanding the full context of a scene before translating individual subtitles.

    **Task:**  Translate the provided batch of subtitles from **{input_language}** to **{output_language}**, strictly adhering to professional subtitling conventions.  Pay special attention to sentence continuity across multiple subtitle entries.

    **Input Subtitles (JSON Array - Batch of 20):**

    {batches_data}

    **Instructions:**

    Instructions:

    1️⃣ Holistic Understanding:
    🔸 Before translating individual subtitles, carefully read all transcripts within the provided batch to grasp the overall context, storyline, character interactions, and any ongoing conversations.
    🔸 Identify Key Elements: Identify key nouns, pronouns, proper nouns, objects, places, and other relevant elements in {input_language} to ensure they remain unchanged for accurate and consistent translation.
    🔸 Identify complete sentences that may span multiple subtitle entries.

    2️⃣ Sentence-Level Translation and Segmentation (CRITICAL):
    🔸 Translate the entire sentence as a whole, even if it spans multiple subtitle entries. Ensure the complete meaning is conveyed in the Simplification Focused translation. Use simple, conversational {output_language}. Avoid formal or complex vocabulary unless necessary.
    🔸 After translating the full sentence, segment the translated text to fit the original subtitle breaks. Ensure that each segment maintains the flow and meaning of the complete sentence, aligning with the original subtitle timing.
    🔸 Sentence Continuity Focus: Ensure that the translation of sentences spanning multiple subtitles maintains the flow and meaning across all relevant subtitle entries.

    3️⃣ Adhere to Subtitle Guidelines: 

        🔸 Accuracy and Clarity: Convey the precise meaning and tone in clear, natural-sounding {output_language}. Avoid literal translations. Provide concise, conversational translations. Do not add descriptions or interpretations.
        🔸 Grammar and Spelling: Ensure impeccable grammar and spelling in {output_language}.
        🔸 Conciseness: Keep subtitles concise without omitting crucial information.
        🔸 Punctuation and Quotes:
        * Single Quotes ('...'): Dialogues, internal monologues, voiceovers, quotes, poems, mantras, flashbacks/recaps.
        * Double Quotes ("..."): Song lyrics only (use ?, ! within lyrics, not , or .). Capitalize each line of a song.
        🔸 Dialogue Separation: Separate multiple speakers' dialogues within a single entry with a hyphen (-).
        🔸 Incomplete Sentences: Use an ellipsis (...) for incomplete sentences. If the next entry continues the thought, begin that sentence with a capital letter.
        🔸 Cultural Adaptation: Adapt culturally specific terms/phrases for the {output_language} audience while maintaining the original meaning. Use single quotes if no direct equivalent exists.{arabic_rule}

    4️⃣ Output in JSON Dict (Final, Verified Translations): Provide your final, verified output in JSON format, ensuring accurate subtitle segmentation:

    ```json
            [
                "number": "[Original Subtitle Number]",
                "text": "[Original Text]",
                "translated_text": "[Your Translated Text in {output_language}]",

                "number": "[Original Subtitle Number]",
                "text": "[Original Text]",
                "translated_text": "[Your Translated Text in {output_language}]",
              // ... (rest of the translated subtitles)
            ]
    ```
    """
    return default_prompt


def generate_qc_translation_prompt(srt_transcript_batch_data, script_batch_data, input_language, output_language):
    """
    Builds a translation prompt with script context for character/gender verification.

    Purpose:
        Produces a prompt that includes both subtitle batch and aligned script context for
        accurate character, gender, and relationship handling in the target language.

    Args:
        srt_transcript_batch_data: list — Primary subtitle batch to translate.
        script_batch_data: list — Aligned script context (speaker, dialogue) for verification.
        input_language: str — Source language.
        output_language: str — Target language.

    Returns:
        str: The full prompt string for the LLM.

    Side effects / Errors:
        None.
    """
    # Dump both data sets to JSON strings
    srt_batch_json = json.dumps(srt_transcript_batch_data)
    script_context_json = json.dumps(script_batch_data)

    arabic_rule = ""
    if output_language.lower() == "arabic":
        arabic_rule = "\n    🔸 **Arabic Dialect Restriction:** When translating to Arabic, you MUST use Modern Standard Arabic (MSA) only. Do NOT use Saudi dialect, Egyptian dialect, or any other regional dialect. All translations must be in standard Arabic dialect that is universally understood across all Arabic-speaking regions. All numbers must be written using standard English digits (1, 2, 3) — not Arabic-Indic digits (١، ٢، ٣)."

    default_prompt = f"""
    You are a highly skilled and meticulous subtitle translator with expertise in translating between various languages while maintaining accuracy, cultural nuance, and natural-sounding dialogue. You strictly adhere to professional subtitling conventions.

    **Task:**  Translate the provided batch of subtitles from **{input_language}** to **{output_language}**, utilizing the accompanying **Script Context** for verification of character, gender, and relationship, and strictly adhering to professional subtitling conventions.

    **Primary Input Subtitles (JSON Array):**
    *   This is the text to be translated and segmented according to its line numbers.

    {srt_batch_json}

    **Script Context (JSON Array):**
    *   This data provides the original, authoritative speaker name and the exact dialogue line from the script source, matching the primary input lines by index. **USE THIS FOR CONTEXT AND CHARACTER VERIFICATION.**

    {script_context_json}

    **Instructions:**

    1️⃣ Contextual and Conversational Translation (CRITICAL):
    🔸 **Use the 'speaker' tag from the Script Context** to verify the character (e.g., LOIS, GENERAL_LANE, JONATHAN).
    🔸 **Character and Gender Verification:** Ensure all pronouns, honorifics, and relational terms (like 'Dad', 'Grandpa', 'sweetie') in the **{output_language}** translation correctly reflect the speaker's and the addressed character's **gender and relationship** (e.g., Lois to Clark, or Jordan to General Lane).
    🔸 **Tone and Style:** The translated text must be **conversational, modern, and suitable for contemporary subtitles**. You must avoid **literal, archaic, Biblical, or overly formal vocabulary** unless explicitly required by the character's persona (which is generally casual for a family drama like 'Superman & Lois').

    2️⃣ Quality Control and Refinement (CRITICAL):
    🔸 **Correct All Errors:** You must meticulously check and **correct any incorrect spelling, verb conjugation, grammatical errors, or awkward phrasing** that may result from initial literal translation attempts. The final **{output_language}** quality must be impeccable.
    🔸 **Holistic Understanding:** Read the full batch of dialogue and the context to translate complete sentences spanning multiple subtitle entries.

    3️⃣ Subtitle Guidelines: 
    🔸 **Accuracy:** Convey the precise meaning and tone. Avoid adding descriptions or interpretations.
    🔸 **Conciseness:** Keep subtitles concise.
    🔸 **Punctuation:** Use single quotes ('...') for dialogue, voiceovers, quotes, etc. Use double quotes ("...") for song lyrics only.
    🔸 **Dialogue Separation:** Separate multiple speakers' dialogues within a single entry with a hyphen (-).
    🔸 **Incomplete Sentences:** Use an ellipsis (...) for incomplete sentences.{arabic_rule}

    4️⃣ Output in JSON Array (Final, Verified Translations): Provide your final, verified output in the exact same structure as the primary input, containing **only** the translated text. Do not include the script context data in the final output.

    ```json
            [
                {{"number": "[Original Subtitle Number]", "text": "[Original Text]", "translated_text": "[Your Translated Text in {output_language}]"}},
              // ... (rest of the translated subtitles)
            ]
    ```
    """
    return default_prompt


def generate_qc_translation_prompt_v3(srt_transcript_batch_data, script_batch_data, input_language, output_language):
    """
    Builds a translation prompt with script context and conversational-tone emphasis.

    Purpose:
        Same as generate_qc_translation_prompt but adds explicit instruction to prioritize
        contemporary, conversational tone and avoid archaic/orthodox vocabulary.

    Args:
        srt_transcript_batch_data: list — Primary subtitle batch to translate.
        script_batch_data: list — Aligned script context for character verification.
        input_language: str — Source language.
        output_language: str — Target language.

    Returns:
        str: The full prompt string for the LLM.

    Side effects / Errors:
        None.
    """
    # Dump both data sets to JSON strings
    srt_batch_json = json.dumps(srt_transcript_batch_data, ensure_ascii=False, indent=4)
    script_context_json = json.dumps(script_batch_data, ensure_ascii=False, indent=4)

    arabic_rule = ""
    if output_language.lower() == "arabic":
        arabic_rule = "\n    🔸 **Arabic Dialect Restriction:** When translating to Arabic, you MUST use Modern Standard Arabic (MSA) only. Do NOT use Saudi dialect, Egyptian dialect, or any other regional dialect. All translations must be in standard Arabic dialect that is universally understood across all Arabic-speaking regions. All numbers must be written using standard English digits (1, 2, 3) — not Arabic-Indic digits (١، ٢، ٣)."

    default_prompt = f"""
    You are a highly skilled and meticulous subtitle translator with expertise in translating between various languages while maintaining accuracy, cultural nuance, and natural-sounding dialogue. You strictly adhere to professional subtitling conventions.

    **Task:** Translate the provided batch of subtitles from **{input_language}** to **{output_language}**, utilizing the accompanying **Script Context** for verification of character, gender, and relationship, and strictly adhering to professional subtitling conventions.

    **Primary Input Subtitles (JSON Array):**
    *   This is the text to be translated and segmented according to its line numbers.

    {srt_batch_json}

    **Script Context (JSON Array):**
    *   This data provides the original, authoritative speaker name and the exact dialogue line from the script source, matching the primary input lines by index. **USE THIS FOR CONTEXT AND CHARACTER VERIFICATION.**

    {script_context_json}

    **Instructions:**

    1️⃣ Contextual and Conversational Translation (CRITICAL):
    🔸 **Use the 'speaker' tag from the Script Context** to verify the character (e.g., LOIS, GENERAL_LANE, JONATHAN).
    🔸 **Character and Gender Verification:** Ensure all pronouns, honorifics, and relational terms (like 'Dad', 'Grandpa', 'sweetie') in the **{output_language}** translation correctly reflect the speaker's and the addressed character's **gender and relationship** (e.g., Lois to Clark, or Jordan to General Lane).
    🔸 **Tone and Style (Highest Priority):** The translated text must be **conversational, contemporary, and suitable for daily, natural speech**. You must **strictly avoid overly literal, archaic, Biblical, or Orthodox vocabulary** unless the source character is explicitly speaking in an outdated style. The goal is a non-literal, fluent translation (e.g., translating "I love you" as the most commonly spoken, intimate expression, not the most formal, textbook version).

    2️⃣ Sentence-Level Translation and Segmentation (CRITICAL):
    🔸 **Holistic Understanding:** Read the full batch of dialogue and the context to translate complete sentences spanning multiple subtitle entries.
    🔸 **Translate the entire sentence as a whole,** even if it spans multiple subtitle entries. Ensure the complete meaning is conveyed in the translation. Use simple, conversational **{output_language}**.
    🔸 **Segmentation:** After translating the full sentence, segment the translated text to fit the original subtitle breaks. Ensure that each segment maintains the flow and meaning of the complete sentence, aligning with the original subtitle timing.

    3️⃣ Quality Control and Refinement (CRITICAL):
    🔸 **Correct All Errors:** You must meticulously check and **correct any incorrect spelling, verb conjugation, grammatical errors, or awkward phrasing** that may result from initial literal translation attempts. The final **{output_language}** quality must be impeccable.
    🔸 **Pronoun/Verb Agreement:** Ensure perfect agreement of verbs and pronouns with the gender, number, and formality level of the characters.

    4️⃣ Subtitle Guidelines: 
    🔸 **Accuracy:** Convey the precise meaning and tone. Avoid adding descriptions or interpretations.
    🔸 **Conciseness:** Keep subtitles concise.
    🔸 **Punctuation:** Use single quotes ('...') for dialogue, voiceovers, quotes, etc. Use double quotes ("...") for song lyrics only.
    🔸 **Dialogue Separation:** Separate multiple speakers' dialogues within a single entry with a hyphen (-).
    🔸 **Incomplete Sentences:** Use an ellipsis (...) for incomplete sentences.{arabic_rule}

    5️⃣ Output in JSON Array (Final, Verified Translations): Provide your final, verified output in the exact same structure as the primary input, containing **only** the translated text. Do not include the script context data in the final output.

    ```json
            [
                {{"number": "[Original Subtitle Number]", "text": "[Original Text]", "translated_text": "[Your Translated Text in {output_language}]"}},
              // ... (rest of the translated subtitles)
            ]
    ```
    """
    return default_prompt


def generate_qc_correction_prompt(srt_parsed_data, script_text):
    """
    Builds a prompt to correct AI transcription using a master script (transcription QC).

    Purpose:
        Instructs the LLM to fix spelling, proper nouns, and punctuation in the SRT by
        aligning with the script, while strictly preserving start/end timecodes and line breaks.

    Args:
        srt_parsed_data: list — SRT entries (e.g., index, start, end, text).
        script_text: str — Raw production script text (ground truth).

    Returns:
        str: The full correction prompt string.

    Side effects / Errors:
        None.
    """
    
    # Dump SRT data to JSON for the LLM to process structurally
    srt_json = json.dumps(srt_parsed_data, ensure_ascii=False, indent=2)

    prompt = f"""
You are an expert Post-Production QC Specialist. You are provided with two inputs:
1. **AI Transcription (JSON):** Subtitles with perfect timecodes but containing errors (typos, wrong names, phonetic mistakes).
2. **Master Script (Text):** The official script containing the correct dialogue, spelling, and speaker names.

**YOUR GOAL:** 
Correct the `text` inside the **AI Transcription** so it matches the **Master Script**, while strictly **PRESERVING the original `start` and `end` timecodes** from the AI Transcription.

**INPUT DATA:**

**1. AI Transcription (To be Corrected):**
{srt_json}

**2. Master Script (Ground Truth / Reference):**
{script_text}

---

**CRITICAL INSTRUCTIONS:**

1️⃣ **ALIGNMENT STRATEGY (The "Golden Master" Rule):**
   - Read the **Master Script** to understand the true content.
   - Locate the corresponding lines in the **AI Transcription**.
   - **REPLACE** the imperfect text in the AI Transcription with the accurate text from the Master Script.
   - *Example:* 
     - AI says: "Mamb mentality"
     - Script says: "Mamba mentality"
     - **Result:** You must change it to "Mamba mentality".

2️⃣ **HANDLING PROPER NOUNS & NAMES:**
   - Pay extreme attention to names (e.g., "Kenny Dobbs", "Mary Rose", "Rucker Park").
   - The AI often misspells these (e.g., "Ken Dobbs"). **You MUST enforce the spelling found in the Master Script.**

3️⃣ **SEGMENTATION & TIMING (Do Not Touch):**
   - **NEVER change the `start` or `end` timecodes.**
   - **NEVER change the `index` numbers.**
   - **PRESERVE LINE BREAKS:** You must maintain the exact line break structure of the AI Transcription. If the original AI text has a line break (`\n`), your corrected text **MUST** include a line break (`\n`) in the corresponding position to maintain the visual format.
   - If the Script has a long sentence but the AI Transcription splits it into two subtitles, you must keep the split. Distribute the corrected Script text across the existing splits logically.
   
4️⃣ **FALLBACK STRATEGY (Unmatched Lines):**
   - If the AI Transcription contains a line (e.g., an ad-lib like "Yeah!" or "Let's go!") that is **NOT** in the Master Script:
     - **KEEP the AI Transcription text.**
     - Do not delete the subtitle entry.
     - Just fix basic punctuation/capitalization if needed.

5️⃣ **SCRIPT PARSING:**
   - The Master Script may contain metadata (e.g., "00:00:02 Kenny Dobbs:", "GRAPHICS AUDIO", "INSIGHT TV"). 
   - **IGNORE** metadata, scene headers, and speaker names (unless the speaker name is part of the dialogue). Only extract the *spoken dialogue* to correct the subtitles.

6️⃣ **OUTPUT FORMAT:**
   Output in JSON Dict (Final, Verified Corrected Text): Provide your final, verified output in JSON format, ensuring accurate subtitle segmentation:

    ```json
            [
                "number": "[Original Subtitle Number]",
                "text": "[Original Text]",
                "corrected_text": "[Your Corrected Text]",

                "number": "[Original Subtitle Number]",
                "text": "[Original Text]",
                "corrected_text": "[Your Corrected Text]",
              // ... (rest of the Corrected subtitles)
            ]
    ```
"""
    return prompt


def generate_confidence_scoring_prompt(batch_data, input_language, output_language):
    """
    Builds a prompt for word-level confidence scoring between original and AIQC-processed text.

    Purpose:
        Produces a prompt that instructs the LLM to compare "text" vs "updated_text" and output
        a 0–100 confidence score per entry. Identical words (after whitespace normalization) = 100.

    Args:
        batch_data: list — Entries with 'id', 'text' (original), 'updated_text' (AIQC-processed).
        input_language: str — Language of the transcription (for context).
        output_language: str — Unused; kept for API compatibility.

    Returns:
        str: The full confidence-scoring prompt.

    Side effects / Errors:
        None.
    """
    prompt = f"""Perform a word-by-word comparison between "text" (original) and "updated_text" (AIQC-processed) and calculate confidence score (0-100) based ONLY on word-level differences.

**CRITICAL RULE - IDENTICAL TEXTS:**
- If "text" and "updated_text" have the SAME WORDS in the SAME ORDER (ignoring only whitespace normalization), confidence MUST be 100
- Normalize whitespace (multiple spaces → single space, trim edges) before comparison
- If words match exactly after normalization → confidence = 100 (no exceptions)

**Scoring Algorithm (for non-identical texts):**
1. Count total words in both texts (use the longer text as denominator)
2. Count matching words in same positions
3. Calculate: (matching_words / total_words) × 100, then adjust for word order differences

**Scoring Guidelines:**
- **100**: Words are identical in same order (after whitespace normalization)
- **95-99**: Same words, only punctuation/capitalization differs (no word additions/deletions/changes)
- **90-94**: 1-2 words different (added/removed/changed), rest identical
- **80-89**: 3-5 words different, majority words match
- **70-79**: 6-10 words different, some words match
- **50-69**: 11-20 words different, few words match
- **0-49**: Most/all words different

**Comparison Method:**
1. Normalize whitespace in both texts (trim, collapse multiple spaces)
2. Split into word lists (preserve order)
3. Compare word-by-word positionally
4. If all words match → 100
5. If words differ → calculate based on word match percentage

**Input:**
```json
{json.dumps(batch_data, ensure_ascii=False, indent=2)}
```

**Output:** JSON array only (no explanations, no markdown):
```json
[
    {{"id": "[original_id]", "confidence": [score_0_to_100]}},
    {{"id": "[original_id]", "confidence": [score_0_to_100]}}
]
```

**Requirements:**
- Output ONLY valid JSON, no other text
- Each output entry must have matching "id" from input
- Integer scores 0-100
- IDENTICAL WORDS (after whitespace normalization) = 100 (mandatory, no exceptions)
- Base score on word differences, not quality assessment
"""
    return prompt


# ======================================================================
# Translation QC / AIQC prompts (from geminiTranslationQC)
# ======================================================================

def generate_character_extraction_prompt(script_text, target_language):
    """
    Builds a prompt to extract character data (names, gender, relationships) from a script.

    Purpose:
        Produces a prompt for localization: extract speaking characters, infer demographics,
        and provide target-language translations for names and kinship terms.

    Args:
        script_text: str — Full episode dialogue list and credits.
        target_language: str — Target language (e.g., "Hindi", "Spanish", "French").

    Returns:
        str: The full character-extraction prompt.

    Side effects / Errors:
        None.
    """
    prompt = f"""You are an AI localization specialist tasked with preparing comprehensive character data for subtitle translation. Given a full TV episode script (dialogue list and credits) and a specified target language, your goal is to extract all character details, infer demographics, and provide accurate, contextually-specific translations for names and family relationships in the target language.

Input Variables:
Source Script Text: The complete text of the episode's dialogue list and credits.
Target Language: The language for translation (e.g., "Hindi," "Spanish," "French," "Kannada").

Instructions:
Character Identification & Filtering: Identify every unique speaking character listed in the TIMECODE CHARACTER DIALOGUE list, and any key named entities from the dialogue or CREDITS (e.g., Doomsday, Elizabeth, Janet).

Detail Extraction & Inference (Source):
Gender: Determine based on dialogue/context (e.g., "Mom," "General Lane," "Female Nurse").
Age (Estimated): Infer a general range based on context (e.g., Teenager, Adult, Senior) and relationships (e.g., 'Dad' is likely 'Adult').
Role/Details: Summarize the character's role and key characteristics from the script notes and dialogue (e.g., "Lois's husband," "Main Antagonist," "Twin brother," "U.S. Army General").

Translation & Transliteration (Target Language):
Character Name (Target Language): Transliterate the character's name into the script of the Target Language.
Family Relationship (Target Language): Identify all explicit and inferred family relationships (e.g., "Grandpa," "Dad," "wife," "daughter") and translate them using the most contextually specific term in the Target Language (e.g., use the specific word for maternal grandfather or paternal grandfather as required by the script's context).

Output Formatting: Present the final output as a single Markdown table with exactly six columns in the order listed below.

As an AI localization specialist, analyze the following script text and the target language. Extract all speaking and key listed characters, infer demographic details, and generate a final Markdown table with the following six columns: 'Character Name', 'Gender', 'Age (Estimated)', 'Role/Details', 'Character Name (target language)', and the correct, contextually specific 'Family Relationship (target language)'.

TARGET_LANGUAGE: [{target_language}]
SOURCE_SCRIPT_TEXT:
{script_text}
"""
    return prompt


def extract_character_str_from_script(script_text, target_language, kafkaMessageParser, model_name=None):
    """
    Calls Gemini to extract character data from a script and returns a Markdown table.

    Purpose:
        Uses generate_character_extraction_prompt and callingGemini to get character names,
        genders, relationships, and target-language translations for use in translation QC.

    Args:
        script_text: str — Full script text to analyze.
        target_language: str — Target language for character name/relationship translation.
        kafkaMessageParser: Parser with llmKey, llmModel, GCP/Vertex settings.
        model_name: str, optional — Override model; defaults to kafkaMessageParser.llmModel.

    Returns:
        str | None: Extracted character info as Markdown table, or None on failure/empty input.

    Side effects / Errors:
        Prints warnings on empty script or missing llmKey. Returns None on exception or API failure.
    """
    if not script_text or not script_text.strip():
        print("Warning: Empty script text provided for character extraction")
        return None
    
    try:
        # Generate the prompt
        prompt = generate_character_extraction_prompt(script_text, target_language)
        
        # Prepare messages for Gemini API call
        messages = [
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        # Use model from kafkaMessageParser if not provided
        if not model_name:
            model_name = kafkaMessageParser.llmModel if hasattr(kafkaMessageParser, 'llmModel') else GEMINI_MODEL_NAME
        
        # Configure Gemini API key
        api_key = None
        if hasattr(kafkaMessageParser, 'llmKey') and kafkaMessageParser.llmKey:
            genai.configure(api_key=kafkaMessageParser.llmKey)
            api_key = kafkaMessageParser.llmKey
        else:
            print("Warning: No llmKey found in kafkaMessageParser, using default")
        
        # Call Gemini to extract character information (with Gemini 3 / Vertex AI support)
        print(f"Calling Gemini to extract character information for target language: {target_language}")
        character_str, prompt_tokens, completion_tokens, result_type = callingGemini(
            messages, model_name,
            api_key=api_key,
            gcp_project=getattr(kafkaMessageParser, 'llmGcpProject', None) or getattr(kafkaMessageParser, 'googleProjectId', None),
            gcp_location=getattr(kafkaMessageParser, 'llmGcpLocation', None),
            thinking_level=getattr(kafkaMessageParser, 'llmThinkingLevel', None),
            temperature=getattr(kafkaMessageParser, 'llmTemperature', None),
            top_p=getattr(kafkaMessageParser, 'llmTopP', None),
            use_gemini_client=getattr(kafkaMessageParser, 'llmUseGeminiClient', False)
        )
        
        if character_str:
            print(f"Successfully extracted character information ({len(character_str)} characters)")
            return character_str
        else:
            print("Warning: Failed to extract character information from script")
            return None
            
    except Exception as e:
        print(f"Exception while extracting character information from script: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_master_correction_prompt_v3(
        source_language_name,
        target_language_name,
        source_batch_str,
        translation_batch_str
):
    """
    Builds AIQC_V3: language-agnostic translation QC prompt (no character data).

    Purpose:
        Master-level prompt for correcting AI translations. Emphasizes contextual inference,
        transliteration into the target script, and natural fluency. Examples are framed
        as universal principles adapted to the specified target language.

    Args:
        source_language_name: str — Source language (e.g., "Malay").
        target_language_name: str — Target language (e.g., "English").
        source_batch_str: str | dict — Source subtitle blocks (dict with "transcripts" is unwrapped).
        translation_batch_str: str | dict — Initial translation blocks to correct.

    Returns:
        str: The full AIQC prompt for the LLM.

    Side effects / Errors:
        None. Mutates batch args in-place if they are dicts with "transcripts".
    """
    if isinstance(source_batch_str, dict) and 'transcripts' in source_batch_str:
        source_batch_str = source_batch_str['transcripts']
    if isinstance(translation_batch_str, dict) and 'transcripts' in translation_batch_str:
        translation_batch_str = translation_batch_str['transcripts']

    arabic_rule = ""
    if target_language_name.lower() == "arabic":
        arabic_rule = "\n\n3.  **Arabic Dialect Restriction:** When translating to Arabic, you MUST use Modern Standard Arabic (MSA) only. Do NOT use Saudi dialect, Egyptian dialect, or any other regional dialect. All translations must be in standard Arabic dialect that is universally understood across all Arabic-speaking regions. All numbers must be written using standard English digits (1, 2, 3) — not Arabic-Indic digits (١، ٢، ٣)."

    example_output_json_structure = """```json
[
  {
    "number": "[Original Subtitle Number]",
    "source_text": "[The original text from the Source Subtitles]",
    "initial_translation": "[The original, uncorrected text from the Initial Translation]",
    "corrected_translation": "[Your final, context-aware, fluently-phrased, and correctly formatted translation]"
  },
  // ... (repeat for ALL subtitle blocks)
]
```"""

    # This example remains the same, as its purpose is to show the workflow.
    # The new instructions in the prompt will tell the model how to interpret it.
    example_entry_explanation = f"""
    **Illustrative Example of the Full Workflow**

    **NOTE:** The following detailed example uses **English-to-Hindi** for demonstration purposes ONLY. You **MUST** apply the same *principles and logical steps* to the **{source_language_name}-to-{target_language_name}** task you have been given.

    *   **Source Subtitles (Blocks 17 & 18):**
        `Subtitles:[{{'number': 17, 'text': 'This shit makes everything delicious.'}}, {{'number': 18, 'text': "Oh, shit. I have Addies\\nif you wanna be skinny tweakers."}}]`

    *   **Initial Translation (Blocks 17 & 18):**
        `Subtitles:[{{'number': 17, 'text': 'ये सब कुछ टेस्टी बना देता है।'}}, {{'number': 18, 'text': 'ओ, यार। मेरे पास Addies भी हैं,\\nअगर पतला होना है तो।'}}]`

    **Your Internal Thought Process (Applying the Chain of Thought):**

    1.  **Reconstruct:** The full thought is "This shit makes everything delicious. Oh, shit. I have Addies if you wanna be skinny tweakers."

    2.  **Diagnose (Using the QC Checklist):**
        *   **Block 17:** `Naturalness & Lexical Mismatch` - "ये सब कुछ टेस्टी बना देता है" is a bit literal. "This shit" is colloquially translated better as "ये चीज़" and "delicious" as "मज़ेदार".
        *   **Block 18:** `Transliteration Policy Violation` - "Addies" must be transliterated. `Contextual & Inferential Accuracy` - "skinny tweakers" implies not just being thin, but also being "high" or hyper, a key nuance the initial translation misses.

    3.  **Synthesize (Holistic Correction for Natural Flow):** I will rewrite both parts to be fluent, natural, and policy-compliant.
        *   *Perfected Sentence 1:* "ये चीज़ सब कुछ मज़ेदार बना देती है।"
        *   *Perfected Sentence 2:* "ओह, मेरे पास एड्डीज़ भी हैं, अगर पतला और हाइपर रहना है तो।" (This version adds the missing "hyper" context and fixes the transliteration).

    4.  **Deconstruct & Apply Intelligent Line Breaks:** Now I will map my perfect sentences back to the original blocks and apply line break rules individually.
        *   **Map to Block 17:** The corrected text is "ये चीज़ सब कुछ मज़ेदार बना देती है।".
        *   **Line Break Logic for 17:** This corrected sentence is short and well under the ~42 character limit. **No line break is needed.**
        *   **Final text for block 17:** "ये चीज़ सब कुछ मज़ेदार बना देती है।"
        *   **Map to Block 18:** The corrected text is "ओह, मेरे पास एड्डीज़ भी हैं, अगर पतला और हाइपर रहना है तो।".
        *   **Line Break Logic for 18:** This corrected sentence is now longer and exceeds the readability limit for a single line. The source also had a break. I will **add a line break** at a logical point. The comma after "हैं" is a natural clause separator and a perfect place for the break.
        *   **Final text for block 18:** "ओह, मेरे पास एड्डीज़ भी हैं,\\nअगर पतला और हाइपर रहना है तो।"

    **Expected Output Snippet (JSON for Blocks 17 & 18):**
   ```json
    [
      // ... (other blocks)
      {{
        "number": "17",
        "source_text": "This shit makes everything delicious.",
        "initial_translation": "ये सब कुछ टेस्टी बना देता है।",
        "corrected_translation": "ये चीज़ सब कुछ मज़ेदार बना देती है।"
      }},
      {{
        "number": "18",
        "source_text": "Oh, shit. I have Addies\\nif you wanna be skinny tweakers.",
        "initial_translation": "ओ, यार। मेरे पास Addies भी हैं,\\nअगर पतला होना है तो।",
        "corrected_translation": "ओह, मेरे पास एड्डीज़ भी हैं,\\nअगर पतला और हाइपर रहना है तो।"
      }}
      // ... (and so on)
    ]
    ```
    *Notice in this new example:*
    1.  The line break was **omitted** from Block 17 because the final text was short and readable.
    2.  The line break was **intelligently added** to Block 18 because the final text was long and needed it for readability.
    3.  This demonstrates that you must evaluate the need for a line break based on the **final corrected text**, not just the source formatting.
    """

    prompt = f"""
You are an expert-level, language-agnostic Subtitle Localization and Quality Control (QC) Specialist. You are a master of both **{source_language_name}** and **{target_language_name}**. Your task is to elevate an AI translation to human-mastery level by applying a universal set of principles for quality. You must focus on three core areas beyond basic fluency: 1) Deep Contextual Inference, 2) Strict Transliteration Policy, and 3) Perfect Orthographic Precision.

Your **ENTIRE RESPONSE MUST BE A SINGLE, VALID JSON ARRAY**.

**Core Methodology: Think, Don't Just Translate**
Your primary directive is to understand the *unspoken context* of the scene and ensure the translation reflects that reality. You must correct translations that are literally correct but contextually wrong. You will rigorously apply the rules and checklist below.

---
**CRITICAL RULE: Transliteration of All Proper Nouns & Brands**

1.  **Transliterate Proper Nouns into the Target Script:** This is a non-negotiable directive. All proper nouns (names, brands, places) from the source MUST be phonetically represented using the native alphabet of the **{target_language_name}**. Do not leave them in the source script.
    *   **ILLUSTRATION OF THE PRINCIPLE:** For English-to-Hindi, "Paula" becomes "पॉला". For English-to-Japanese, "Paula" would become "ポーラ". You must perform the correct transliteration for the specified **{target_language_name}**.

2.  **Final Output Must ONLY Contain the Target Language:** The `corrected_translation` field must be entirely in **{target_language_name}**, with the only exception being globally recognized initialisms (e.g., "NASA"). Do not mix scripts.{arabic_rule}

---

**Input Data:**

1.  **Source Subtitles (Ground Truth for Meaning and Context):**
    ```
    {json.dumps(source_batch_str, indent=2, ensure_ascii=False)}
    ```

2.  **Initial Translation (To Be Corrected):**
    ```
    {json.dumps(translation_batch_str, indent=2, ensure_ascii=False)}
    ```

**Chain of Thought for Correction (Follow these steps meticulously):**

**Step 1: Reconstruct Full Sentences & Understand Scene Context**
a.  Stitch together fragmented blocks to form complete sentences.
b.  Crucially, analyze the surrounding dialogue to understand the full situation, character intent, and any unstated objects or ideas being discussed.

**Step 2: Diagnose the Full Sentence Holistically (Your QC Checklist)**
a.  For each complete sentence, use this enhanced **QC Checklist**.
b.  **Your QC Checklist:**
    *   **`Naturalness & Colloquial Tone` (High Priority):** Does this sound like a native speaker talking, or a textbook? Fix any phrasing that is grammatically correct but feels unnatural, stiff, or robotic.
    *   **`Contextual & Inferential Accuracy` (CRITICAL):** Does the translation capture the *unspoken meaning*? Is it reacting only to the literal words, or to the character's full intent?  Example: "I don't have anything to smoke *it* with" implies a lack of a *device*. Your translation must capture this inferred meaning.
    *   **`Transliteration Policy Adherence`**: Have all **{source_language_name}** proper nouns been correctly transliterated into the **{target_language_name}** script as per Critical Rule #1?
    *   **`Grammatical & Orthographic Error`**: Are there any mistakes in grammar or spelling? Pay close attention to orthographic details relevant to the **{target_language_name}** (e.g., accents, diacritics, special characters like Hindi nuktas or German umlauts).
    *   **`Semantic Divergence`:** Is the core meaning lost, changed, or twisted?
    *   **`Lexical Mismatch`**: Are the word choices imprecise? Replace unnatural words with more common, colloquial alternatives.

**Step 3: Synthesize the Corrected Translation**
a.  Based on your diagnosis, construct a new, perfect `corrected_translation` for the entire sentence, resolving ALL identified issues. This version should be both contextually accurate and sound perfectly natural.

**Step 4: Deconstruct, Map Back, and Apply Intelligent Line Breaks**
a.  Take your perfected, full-sentence translation from Step 3.
b.  Carefully map this corrected text back onto the original subtitle blocks it corresponds to.
c.  **Intelligent Line Breaking Rules (`\\n`):** Apply professional subtitling standards for readability within each block.
    i.   **Evaluate Necessity:** A break is needed if text exceeds **~42 characters** or if the source had a break and the corrected text is still substantially long.
    ii.  **Find the Optimal Break Point:** Prefer breaking after punctuation (commas) or before conjunctions/prepositions. Avoid breaking names.
    iii. **Ensure Visual Balance:** Avoid very short "orphaned" lines. Strive for balanced line lengths. The primary goal is readability.
    iv. **Single Break per Block:** Use a maximum of one `\\n` per block, placed at the most logical and readable point.

**Step 5: Final Assembly**
a.  For each block, create a final JSON object with the keys: `number`, `source_text`, `initial_translation`, and your final `corrected_translation`.
b.  Assemble ALL of these objects into **ONE SINGLE JSON ARRAY**.

---
**Output Format and Advanced Process Example**

First, here is the strict JSON structure for your output:
{example_output_json_structure}

Second, here is a detailed example of the advanced thought process you must use:
{example_entry_explanation}

---

Now, apply this advanced, context-driven, language-agnostic methodology to the provided data and generate the **single, complete, and impeccably corrected** JSON output.
"""
    return prompt


def generate_master_correction_prompt_v4(
        source_language_name,
        target_language_name,
        source_batch_str,
        translation_batch_str,
        character_data_str  # <--- NEW PARAMETER
):
    """
    Builds AIQC_V4: translation QC prompt with character data for gender/kinship precision.

    Purpose:
        Extends V3 by integrating character_data_str for grammatical gender, social address
        forms, and kinship terminology (e.g., maternal vs paternal grandfather).

    Args:
        source_language_name: str — Source language.
        target_language_name: str — Target language.
        source_batch_str: str | dict — Source subtitle blocks.
        translation_batch_str: str | dict — Initial translation blocks to correct.
        character_data_str: str — Character names, genders, relationships (Markdown table).

    Returns:
        str: The full AIQC prompt for the LLM.

    Side effects / Errors:
        None. Mutates batch args in-place if they are dicts with "transcripts".
    """
    if isinstance(source_batch_str, dict) and 'transcripts' in source_batch_str:
        source_batch_str = source_batch_str['transcripts']
    if isinstance(translation_batch_str, dict) and 'transcripts' in translation_batch_str:
        translation_batch_str = translation_batch_str['transcripts']

    example_output_json_structure = """```json
[
  {
    "number": "[Original Subtitle Number]",
    "source_text": "[The original text from the Source Subtitles]",
    "initial_translation": "[The original, uncorrected text from the Initial Translation]",
    "corrected_translation": "[Your final, context-aware, fluently-phrased, and correctly formatted translation]"
  },
  // ... (repeat for ALL subtitle blocks)
]
```"""

    # This example remains the same, as its purpose is to show the workflow.
    example_entry_explanation = f"""
    **Illustrative Example of the Full Workflow (English-to-Hindi)**

    **NOTE:** This example illustrates the *principles* you **MUST** apply to the **{source_language_name}-to-{target_language_name}** task, especially focusing on contextual and social precision.

    *   **Source Subtitles (Blocks 17 & 18):**
        `Subtitles:[{{'number': 17, 'text': 'This shit makes everything delicious.'}}, {{'number': 18, 'text': "Oh, shit. I have Addies\\nif you wanna be skinny tweakers."}}]`

    *   **Initial Translation (Blocks 17 & 18):**
        `Subtitles:[{{'number': 17, 'text': 'ये सब कुछ टेस्टी बना देता है।'}}, {{'number': 18, 'text': 'ओ, यार। मेरे पास Addies भी हैं,\\nअगर पतला होना है तो।'}}]`

    **Your Internal Thought Process (Applying the Chain of Thought):**

    1.  **Reconstruct & Consult Character Data:** The full thought is "This shit makes everything delicious. Oh, shit. I have Addies if you wanna be skinny tweakers." *I'll verify the speaker's gender/relationship from the provided Character Data to ensure correct Hindi verb endings.*

    2.  **Diagnose (Using the QC Checklist):**
        *   **Block 17:** `Naturalness & Lexical Mismatch` - "ये सब कुछ टेस्टी बना देता है" is a bit literal. "This shit" is colloquially better as "ये चीज़" and "delicious" as "मज़ेदार".
        *   **Block 18:** `Transliteration Policy Violation` - "Addies" must be transliterated. `Contextual & Inferential Accuracy` - "skinny tweakers" implies not just being thin, but also being "high" or hyper, a key nuance the initial translation misses. *Also checked: speaker/addressee are peers, so informal address is correct.*

    3.  **Synthesize (Holistic Correction for Natural Flow):** I will rewrite both parts to be fluent, natural, and policy-compliant.
        *   *Perfected Sentence 1:* "ये चीज़ सब कुछ मज़ेदार बना देती है।"
        *   *Perfected Sentence 2:* "ओह, मेरे पास एड्डीज़ भी हैं, अगर पतला और हाइपर रहना है तो।" (This version adds the missing "hyper" context and fixes the transliteration).

    4.  **Deconstruct & Apply Intelligent Line Breaks:** Now I will map my perfect sentences back to the original blocks and apply line break rules individually.
        *   **Map to Block 17:** The corrected text is "ये चीज़ सब कुछ मज़ेदार बना देती है।".
        *   **Line Break Logic for 17:** This corrected sentence is short and well under the ~42 character limit. **No line break is needed.**
        *   **Final text for block 17:** "ये चीज़ सब कुछ मज़ेदार बना देती है।"
        *   **Map to Block 18:** The corrected text is "ओह, मेरे पास एड्डीज़ भी हैं, अगर पतला और हाइपर रहना है तो।".
        *   **Line Break Logic for 18:** This corrected sentence is now longer and exceeds the readability limit. I will **add a line break** at the logical comma.
        *   **Final text for block 18:** "ओह, मेरे पास एड्डीज़ भी हैं,\\nअगर पतला और हाइपर रहना है तो।"

    **Expected Output Snippet (JSON for Blocks 17 & 18):**
   ```json
    [
      // ... (other blocks)
      {{
        "number": "17",
        "source_text": "This shit makes everything delicious.",
        "initial_translation": "ये सब कुछ टेस्टी बना देता है।",
        "corrected_translation": "ये चीज़ सब कुछ मज़ेदार बना देती है।"
      }},
      {{
        "number": "18",
        "source_text": "Oh, shit. I have Addies\\nif you wanna be skinny tweakers.",
        "initial_translation": "ओ, यार। मेरे पास Addies भी हैं,\\nअगर पतला होना है तो।",
        "corrected_translation": "ओह, मेरे पास एड्डीज़ भी हैं,\\nअगर पतला और हाइपर रहना है तो।"
      }}
      // ... (and so on)
    ]
    ```
    """

    prompt = f"""
You are an expert-level, language-agnostic Subtitle Localization and Quality Control (QC) Specialist. You are a master of both **{source_language_name}** and **{target_language_name}**. Your task is to elevate an AI translation to human-mastery level by applying a universal set of principles for quality. You must focus on three core areas beyond basic fluency: 1) Deep Contextual Inference, 2) Strict Transliteration Policy, and 3) Perfect Orthographic and Social Precision.

Your **ENTIRE RESPONSE MUST BE A SINGLE, VALID JSON ARRAY**.

---
**CRITICAL REFERENCE: Character and Contextual Data**

You **MUST** reference this information in Step 1 to infer the correct grammatical gender/number, social address forms (formal/informal), and kinship terminology (e.g., Paternal vs. Maternal terms) for all dialogue:

{character_data_str}

---
**CRITICAL RULE 1: Transliteration of All Proper Nouns & Brands**

1.  **Transliterate Proper Nouns into the Target Script:** This is a non-negotiable directive. All proper nouns (names, brands, places) from the source MUST be phonetically represented using the native alphabet of the **{target_language_name}**. Do not leave them in the source script.
    *   **ILLUSTRATION OF THE PRINCIPLE:** For English-to-Hindi, "Paula" becomes "पॉला". For English-to-Japanese, "Paula" would become "ポーラ". You must perform the correct transliteration for the specified **{target_language_name}**.

2.  **Final Output Must ONLY Contain the Target Language:** The `corrected_translation` field must be entirely in **{target_language_name}**, with the only exception being globally recognized initialisms (e.g., "NASA"). Do not mix scripts.

---
**CRITICAL RULE 2: Contextual & Social Precision (Addresses all Gender/Respect/Kinship issues)**

1.  **Grammatical Agreement:** You **MUST** ensure perfect agreement of verbs, adjectives, and pronouns with the **actual gender and number** of the speaker and the person being addressed, by consulting the Character Data.
2.  **Social Address Forms:** Choose the appropriate social address form (e.g., formal 'आप' vs. informal 'तुम' in Hindi; similar forms in all target languages) based on the relationship context (e.g., child-to-parent, peer-to-peer, boss-to-subordinate).
3.  **Kinship Terminology:** Where the English source uses a generic term (e.g., "Grandad"), you **MUST** use the contextually correct *Target Language* term (e.g., *Nanu* for maternal vs. *Dada* for paternal in Hindi) based on the character's relationship in the provided data.

---

**Input Data:**

1.  **Source Subtitles (Ground Truth for Meaning and Context):**
    ```
    {json.dumps(source_batch_str, indent=2, ensure_ascii=False)}
    ```

2.  **Initial Translation (To Be Corrected):**
    ```
    {json.dumps(translation_batch_str, indent=2, ensure_ascii=False)}
    ```

**Chain of Thought for Correction (Follow these steps meticulously):**

**Step 1: Reconstruct Full Sentences & Understand Scene Context**
a.  Stitch together fragmented blocks to form complete sentences.
b.  Crucially, analyze the surrounding dialogue, **and consult the Character Data**, to understand the full situation, character intent, and any unstated objects or ideas being discussed.

**Step 2: Diagnose the Full Sentence Holistically (Your QC Checklist)**
a.  For each complete sentence, use this enhanced **QC Checklist**.
b.  **Your QC Checklist:**
    *   **`Contextual & Inferential Accuracy` (CRITICAL):** Does the translation capture the *unspoken meaning*? Is it reacting only to the literal words, or to the character's full intent? Fix literal translations that are contextually wrong (e.g., 'space' when 'privacy' is intended, or 'blurry' when 'numb' is intended for a mind/brain).
    *   **`Social & Kinship Term Precision` (CRITICAL):** Is the correct Kinship term used? Are the Social Address Forms (respectful/informal) correct? Is the grammatical gender/number of verbs and pronouns correct for the speaker and addressee?
    *   **`Naturalness & Colloquial Tone` (High Priority):** Does this sound like a native speaker talking, or a textbook? Replace stiff, robotic, or obscure word choices with natural, common, colloquial alternatives.
    *   **`Transliteration Policy Adherence`**: Have all proper nouns been correctly transliterated into the **{target_language_name}** script as per Critical Rule #1?
    *   **`Grammatical & Orthographic Error`**: Are there any mistakes in grammar, spelling, or punctuation (e.g., missing *Poornvirams* or correct use of *Nuktas*)?

**Step 3: Synthesize the Corrected Translation**
a.  Based on your diagnosis, construct a new, perfect `corrected_translation` for the entire sentence, resolving ALL identified issues. This version should be both contextually accurate and sound perfectly natural.

**Step 4: Deconstruct, Map Back, and Apply Intelligent Line Breaks**
a.  Take your perfected, full-sentence translation from Step 3.
b.  Carefully map this corrected text back onto the original subtitle blocks it corresponds to.
c.  **Intelligent Line Breaking Rules (`\\n`):** Apply professional subtitling standards for readability within each block. (Follow all original V3 line breaking rules).

**Step 5: Final Assembly**
a.  For each block, create a final JSON object with the keys: `number`, `source_text`, `initial_translation`, and your final `corrected_translation`.
b.  Assemble ALL of these objects into **ONE SINGLE JSON ARRAY**.

---
**Output Format and Advanced Process Example**

First, here is the strict JSON structure for your output:
{example_output_json_structure}

Second, here is a detailed example of the advanced thought process you must use:
{example_entry_explanation}

---

Now, apply this advanced, context-driven, language-agnostic methodology to the provided data and generate the **single, complete, and impeccably corrected** JSON output.
"""
    return prompt


def generate_master_correction_prompt_v5(
        source_language_name,
        target_language_name,
        source_batch_str,
        translation_batch_str,
        character_data_str
):
    """
    Builds AIQC_V5: translation QC with explicit Gender/Honorific/Relational checklist.

    Purpose:
        Extends V4 by adding specific checklist items for gender, honorifics/respect, and
        overly literal/stiff translations to reduce those error types.

    Args:
        source_language_name: str — Source language.
        target_language_name: str — Target language.
        source_batch_str: str | dict — Source subtitle blocks.
        translation_batch_str: str | dict — Initial translation blocks to correct.
        character_data_str: str — Character data for contextual inference.

    Returns:
        str: The full AIQC prompt for the LLM.

    Side effects / Errors:
        None. Mutates batch args in-place if they are dicts with "transcripts".
    """
    if isinstance(source_batch_str, dict) and 'transcripts' in source_batch_str:
        source_batch_str = source_batch_str['transcripts']
    if isinstance(translation_batch_str, dict) and 'transcripts' in translation_batch_str:
        translation_batch_str = translation_batch_str['transcripts']

    example_output_json_structure = """```json
[
  {
    "number": "[Original Subtitle Number]",
    "source_text": "[The original text from the Source Subtitles]",
    "initial_translation": "[The original, uncorrected text from the Initial Translation]",
    "corrected_translation": "[Your final, context-aware, fluently-phrased, and correctly formatted translation]"
  },
  // ... (repeat for ALL subtitle blocks)
]
```"""

    # This example remains the same, as its purpose is to show the workflow.
    example_entry_explanation = f"""
    **Illustrative Example of the Full Workflow**

    **NOTE:** The following detailed example uses **English-to-Hindi** for demonstration purposes ONLY. You **MUST** apply the same *principles and logical steps* to the **{source_language_name}-to-{target_language_name}** task you have been given.

    *   **Source Subtitles (Blocks 17 & 18):**
        `Subtitles:[{{'number': 17, 'text': 'This shit makes everything delicious.'}}, {{'number': 18, 'text': "Oh, shit. I have Addies\\nif you wanna be skinny tweakers."}}]`

    *   **Initial Translation (Blocks 17 & 18):**
        `Subtitles:[{{'number': 17, 'text': 'ये सब कुछ टेस्टी बना देता है।'}}, {{'number': 18, 'text': 'ओ, यार। मेरे पास Addies भी हैं,\\nअगर पतला होना है तो।'}}]`

    **Your Internal Thought Process (Applying the Chain of Thought):**

    1.  **Reconstruct:** The full thought is "This shit makes everything delicious. Oh, shit. I have Addies if you wanna be skinny tweakers."

    2.  **Diagnose (Using the QC Checklist):**
        *   **Block 17:** `Naturalness & Lexical Mismatch` - "ये सब कुछ टेस्टी बना देता है" is a bit literal. "This shit" is colloquially translated better as "ये चीज़" and "delicious" as "मज़ेदार".
        *   **Block 18:** `Transliteration Policy Violation` - "Addies" must be transliterated. `Contextual & Inferential Accuracy` - "skinny tweakers" implies not just being thin, but also being "high" or hyper, a key nuance the initial translation misses.
        *   **Relational & Honorific Accuracy (New Check):** *Check: The tone is casual/informal, so informal pronouns and verb conjugations are correct.*
        *   **Gender & Inflectional Accuracy (New Check):** *Check: No inflectional errors here.*

    3.  **Synthesize (Holistic Correction for Natural Flow):** I will rewrite both parts to be fluent, natural, and policy-compliant.
        *   *Perfected Sentence 1:* "ये चीज़ सब कुछ मज़ेदार बना देती है।"
        *   *Perfected Sentence 2:* "ओह, मेरे पास एड्डीज़ भी हैं, अगर पतला और हाइपर रहना है तो।" (This version adds the missing "hyper" context and fixes the transliteration).

    4.  **Deconstruct & Apply Intelligent Line Breaks:** Now I will map my perfect sentences back to the original blocks and apply line break rules individually.
        *   **Map to Block 17:** The corrected text is "ये चीज़ सब कुछ मज़ेदार बना देती है।".
        *   **Line Break Logic for 17:** This corrected sentence is short and well under the ~42 character limit. **No line break is needed.**
        *   **Final text for block 17:** "ये चीज़ सब कुछ मज़ेदार बना देती है।"
        *   **Map to Block 18:** The corrected text is "ओह, मेरे पास एड्डीज़ भी हैं, अगर पतला और हाइपर रहना है तो।".
        *   **Line Break Logic for 18:** This corrected sentence is now longer and exceeds the readability limit for a single line. The source also had a break. I will **add a line break** at a logical point. The comma after "हैं" is a natural clause separator and a perfect place for the break.
        *   **Final text for block 18:** "ओह, मेरे पास एड्डीज़ भी हैं,\\nअगर पतला और हाइपर रहना है तो।"

    **Expected Output Snippet (JSON for Blocks 17 & 18):**
   ```json
    [
      // ... (other blocks)
      {{
        "number": "17",
        "source_text": "This shit makes everything delicious.",
        "initial_translation": "ये सब कुछ टेस्टी बना देता है।",
        "corrected_translation": "ये चीज़ सब कुछ मज़ेदार बना देती है।"
      }},
      {{
        "number": "18",
        "source_text": "Oh, shit. I have Addies\\nif you wanna be skinny tweakers.",
        "initial_translation": "ओ, यार। मेरे पास Addies भी हैं,\\nअगर पतला होना है तो।",
        "corrected_translation": "ओह, मेरे पास एड्डीज़ भी हैं,\\nअगर पतला और हाइपर रहना है तो।"
      }}
      // ... (and so on)
    ]
    ```
    *Notice in this new example:*
    1.  The line break was **omitted** from Block 17 because the final text was short and readable.
    2.  The line break was **intelligently added** to Block 18 because the final text was long and needed it for readability.
    3.  This demonstrates that you must evaluate the need for a line break based on the **final corrected text**, not just the source formatting.
    """

    prompt = f"""
You are an expert-level, language-agnostic Subtitle Localization and Quality Control (QC) Specialist. You are a master of both **{source_language_name}** and **{target_language_name}**. Your task is to elevate an AI translation to human-mastery level by applying a universal set of principles for quality. You must focus on three core areas beyond basic fluency: 1) Deep Contextual Inference, 2) Strict Transliteration Policy, and 3) Perfect Orthographic Precision.

Your **ENTIRE RESPONSE MUST BE A SINGLE, VALID JSON ARRAY**.

**Core Methodology: Think, Don't Just Translate**
Your primary directive is to understand the *unspoken context* of the scene and ensure the translation reflects that reality. You must correct translations that are literally correct but contextually wrong. You will rigorously apply the rules and checklist below.

**CRITICAL INFERENCE CHECK (Respect & Relationship):** Before translating, you **MUST** infer the relationship between the speaker and the listener/subject (e.g., child-to-parent, formal business, romantic, maternal vs. paternal relative). This inference **MUST** dictate the choice of pronouns, honorifics, and specific familial terms in the **{target_language_name}**.

{character_data_str}

---
**CRITICAL RULE: Transliteration of All Proper Nouns & Brands**

1.  **Transliterate Proper Nouns into the Target Script:** This is a non-negotiable directive. All proper nouns (names, brands, places) from the source MUST be phonetically represented using the native alphabet of the **{target_language_name}**. Do not leave them in the source script.
    *   **ILLUSTRATION OF THE PRINCIPLE:** For English-to-Hindi, "Paula" becomes "पॉला". For English-to-Japanese, "Paula" would become "ポーラ". You must perform the correct transliteration for the specified **{target_language_name}**.

2.  **Final Output Must ONLY Contain the Target Language:** The `corrected_translation` field must be entirely in **{target_language_name}**, with the only exception being globally recognized initialisms (e.g., "NASA"). Do not mix scripts.

---

**Input Data:**

1.  **Source Subtitles (Ground Truth for Meaning and Context):**
    ```
    {json.dumps(source_batch_str, indent=2, ensure_ascii=False)}
    ```

2.  **Initial Translation (To Be Corrected):**
    ```
    {json.dumps(translation_batch_str, indent=2, ensure_ascii=False)}
    ```

**Chain of Thought for Correction (Follow these steps meticulously):**

**Step 1: Reconstruct Full Sentences & Understand Scene Context**
a.  Stitch together fragmented blocks to form complete sentences.
b.  Crucially, analyze the surrounding dialogue to understand the full situation, character intent, and any unstated objects or ideas being discussed. **Infer and complete any context that a native speaker would understand even if it's missing from the spoken text.** (e.g., completing the phrase "previously on..." or identifying the subject of a fragmented sentence).

**Step 2: Diagnose the Full Sentence Holistically (Your QC Checklist)**
a.  For each complete sentence, use this enhanced **QC Checklist**.
b.  **Your QC Checklist (Revised for V4):**
    *   **`Relational & Honorific Accuracy` (CRITICAL):** Have you correctly applied the required level of respect (formal vs. informal, e.g., 'तुम' vs 'आप' or similar) based on the inferred relationship? Have you used the correct familial terms (e.g., maternal vs. paternal grandfather)?
    *   **`Gender & Inflectional Accuracy` (CRITICAL):** Are all verbs, adjectives, and pronouns correctly inflected (conjugated) to agree with the gender, number, and formality of the speaker and listener in the **{target_language_name}**?
    *   **`Naturalness & Colloquial Tone` (High Priority):** Does this sound like a native speaker talking, or a textbook? Replace any stiff, robotic, or overly literal/biblical phrasing with natural, contemporary colloquialisms.
    *   **`Contextual & Inferential Accuracy` (CRITICAL):** Does the translation capture the *unspoken meaning*? Is it reacting only to the literal words, or to the character's full intent?
    *   **`Transliteration Policy Adherence`**: Have all **{source_language_name}** proper nouns been correctly transliterated into the **{target_language_name}** script as per Critical Rule #1?
    *   **`Semantic Divergence`:** Is the core meaning lost, changed, or twisted?

**Step 3: Synthesize the Corrected Translation**
a.  Based on your diagnosis, construct a new, perfect `corrected_translation` for the entire sentence, resolving ALL identified issues. This version should be both contextually accurate and sound perfectly natural.

**Step 4: Deconstruct, Map Back, and Apply Intelligent Line Breaks**
a.  Take your perfected, full-sentence translation from Step 3.
b.  Carefully map this corrected text back onto the original subtitle blocks it corresponds to.
c.  **Intelligent Line Breaking Rules (`\\n`):** Apply professional subtitling standards for readability within each block.
    i.   **Evaluate Necessity:** A break is needed if text exceeds **~42 characters** or if the source had a break and the corrected text is still substantially long.
    ii.  **Find the Optimal Break Point:** Prefer breaking after punctuation (commas) or before conjunctions/prepositions. Avoid breaking names.
    iii. **Ensure Visual Balance:** Avoid very short "orphaned" lines. Strive for balanced line lengths. The primary goal is readability.
    iv. **Single Break per Block:** Use a maximum of one `\\n` per block, placed at the most logical and readable point.

**Step 5: Final Assembly**
a.  For each block, create a final JSON object with the keys: `number`, `source_text`, `initial_translation`, and your final `corrected_translation`.
b.  Assemble ALL of these objects into **ONE SINGLE JSON ARRAY**.

---
**Output Format and Advanced Process Example**

First, here is the strict JSON structure for your output:
{example_output_json_structure}

Second, here is a detailed example of the advanced thought process you must use:
{example_entry_explanation}

---

Now, apply this advanced, context-driven, language-agnostic methodology to the provided data and generate the **single, complete, and impeccably corrected** JSON output.
"""
    return prompt


def generate_master_correction_prompt_v6(
        source_language_name,
        target_language_name,
        source_batch_str,
        translation_batch_str,
        character_data_str
):
    """
    Builds AIQC_V6: translation QC with conversational-tone priority (avoid archaic/literal).

    Purpose:
        Adds CRITICAL instruction to avoid strictly literal, Orthodox, or archaic language
        in favor of contemporary, non-literal, conversational tone for all target languages.

    Args:
        source_language_name: str — Source language.
        target_language_name: str — Target language.
        source_batch_str: str | dict — Source subtitle blocks.
        translation_batch_str: str | dict — Initial translation blocks to correct.
        character_data_str: str — Character names/relationships for context.

    Returns:
        str: The full AIQC prompt for the LLM.

    Side effects / Errors:
        None. Mutates batch args in-place if they are dicts with "transcripts".
    """
    if isinstance(source_batch_str, dict) and 'transcripts' in source_batch_str:
        source_batch_str = source_batch_str['transcripts']
    if isinstance(translation_batch_str, dict) and 'transcripts' in translation_batch_str:
        translation_batch_str = translation_batch_str['transcripts']

    example_output_json_structure = """```json
[
  {
    "number": "[Original Subtitle Number]",
    "source_text": "[The original text from the Source Subtitles]",
    "initial_translation": "[The original, uncorrected text from the Initial Translation]",
    "corrected_translation": "[Your final, context-aware, fluently-phrased, and correctly formatted translation]"
  },
  // ... (repeat for ALL subtitle blocks)
]
```"""

    # This example remains the same, as its purpose is to show the workflow.
    example_entry_explanation = f"""
    **Illustrative Example of the Full Workflow**

    **NOTE:** The following detailed example uses **English-to-Hindi** for demonstration purposes ONLY. You **MUST** apply the same *principles and logical steps* to the **{source_language_name}-to-{target_language_name}** task you have been given.

    *   **Source Subtitles (Blocks 17 & 18):**
        `Subtitles:[{{'number': 17, 'text': 'This shit makes everything delicious.'}}, {{'number': 18, 'text': "Oh, shit. I have Addies\\nif you wanna be skinny tweakers."}}]`

    *   **Initial Translation (Blocks 17 & 18):**
        `Subtitles:[{{'number': 17, 'text': 'ये सब कुछ टेस्टी बना देता है।'}}, {{'number': 18, 'text': 'ओ, यार। मेरे पास Addies भी हैं,\\nअगर पतला होना है तो।'}}]`

    **Your Internal Thought Process (Applying the Chain of Thought):**

    1.  **Reconstruct:** The full thought is "This shit makes everything delicious. Oh, shit. I have Addies if you wanna be skinny tweakers."

    2.  **Diagnose (Using the QC Checklist):**
        *   **Block 17:** `Naturalness & Conversational Tone` - "ये सब कुछ टेस्टी बना देता है" is a bit literal. "This shit" is colloquially translated better as "ये चीज़" and "delicious" as "मज़ेदार".
        *   **Block 18:** `Transliteration Policy Violation` - "Addies" must be transliterated. `Contextual & Inferential Accuracy` - "skinny tweakers" implies not just being thin, but also being "high" or hyper, a key nuance the initial translation misses.
        *   **Relational & Honorific Accuracy:** *Check: The tone is casual/informal, so informal pronouns and verb conjugations are correct.*
        *   **Gender & Inflectional Accuracy:** *Check: No inflectional errors here.*

    3.  **Synthesize (Holistic Correction for Natural Flow):** I will rewrite both parts to be fluent, natural, and policy-compliant.
        *   *Perfected Sentence 1:* "ये चीज़ सब कुछ मज़ेदार बना देती है।"
        *   *Perfected Sentence 2:* "ओह, मेरे पास एड्डीज़ भी हैं, अगर पतला और हाइपर रहना है तो।" (This version adds the missing "hyper" context and fixes the transliteration).

    4.  **Deconstruct & Apply Intelligent Line Breaks:** Now I will map my perfect sentences back to the original blocks and apply line break rules individually.
        *   **Map to Block 17:** The corrected text is "ये चीज़ सब कुछ मज़ेदार बना देती है।".
        *   **Line Break Logic for 17:** This corrected sentence is short and well under the ~42 character limit. **No line break is needed.**
        *   **Final text for block 17:** "ये चीज़ सब कुछ मज़ेदार बना देती है।"
        *   **Map to Block 18:** The corrected text is "ओह, मेरे पास एड्डीज़ भी हैं, अगर पतला और हाइपर रहना है तो।".
        *   **Line Break Logic for 18:** This corrected sentence is now longer and exceeds the readability limit for a single line. The source also had a break. I will **add a line break** at a logical point. The comma after "हैं" is a natural clause separator and a perfect place for the break.
        *   **Final text for block 18:** "ओह, मेरे पास एड्डीज़ भी हैं,\\nअगर पतला और हाइपर रहना है तो।"

    **Expected Output Snippet (JSON for Blocks 17 & 18):**
   ```json
    [
      // ... (other blocks)
      {{
        "number": "17",
        "source_text": "This shit makes everything delicious.",
        "initial_translation": "ये सब कुछ टेस्टी बना देता है।",
        "corrected_translation": "ये चीज़ सब कुछ मज़ेदार बना देती है।"
      }},
      {{
        "number": "18",
        "source_text": "Oh, shit. I have Addies\\nif you wanna be skinny tweakers.",
        "initial_translation": "ओ, यार। मेरे पास Addies भी हैं,\\nअगर पतला होना है तो।",
        "corrected_translation": "ओह, मेरे पास एड्डीज़ भी हैं,\\nअगर पतला और हाइपर रहना है तो।"
      }}
      // ... (and so on)
    ]
    ```
    *Notice in this new example:*
    1.  The line break was **omitted** from Block 17 because the final text was short and readable.
    2.  The line break was **intelligently added** to Block 18 because the final text was long and needed it for readability.
    3.  This demonstrates that you must evaluate the need for a line break based on the **final corrected text**, not just the source formatting.
    """

    prompt = f"""
You are an expert-level, language-agnostic Subtitle Localization and Quality Control (QC) Specialist. You are a master of both **{source_language_name}** and **{target_language_name}**. Your task is to elevate an AI translation to human-mastery level by applying a universal set of principles for quality. You must focus on three core areas beyond basic fluency: 1) Deep Contextual Inference, 2) Strict Transliteration Policy, and 3) Perfect Orthographic Precision.

Your **ENTIRE RESPONSE MUST BE A SINGLE, VALID JSON ARRAY**.

**Core Methodology: Think, Don't Just Translate**
Your primary directive is to understand the *unspoken context* of the scene and ensure the translation reflects that reality. You must correct translations that are literally correct but contextually wrong. You will rigorously apply the rules and checklist below.

**CRITICAL INFERENCE CHECK (Respect & Relationship):** Before translating, you **MUST** infer the relationship between the speaker and the listener/subject (e.g., child-to-parent, formal business, romantic, maternal vs. paternal relative). This inference **MUST** dictate the choice of pronouns, honorifics, and specific familial terms in the **{target_language_name}**.

{character_data_str}

---
**CRITICAL RULE: Transliteration of All Proper Nouns & Brands**

1.  **Transliterate Proper Nouns into the Target Script:** This is a non-negotiable directive. All proper nouns (names, brands, places) from the source MUST be phonetically represented using the native alphabet of the **{target_language_name}**. Do not leave them in the source script.
    *   **ILLUSTRATION OF THE PRINCIPLE:** For English-to-Hindi, "Paula" becomes "पॉला". For English-to-Japanese, "Paula" would become "ポーラ". You must perform the correct transliteration for the specified **{target_language_name}**.

2.  **Final Output Must ONLY Contain the Target Language:** The `corrected_translation` field must be entirely in **{target_language_name}**, with the only exception being globally recognized initialisms (e.g., "NASA"). Do not mix scripts.

---

**Input Data:**

1.  **Source Subtitles (Ground Truth for Meaning and Context):**
    ```
    {json.dumps(source_batch_str, indent=2, ensure_ascii=False)}
    ```

2.  **Initial Translation (To Be Corrected):**
    ```
    {json.dumps(translation_batch_str, indent=2, ensure_ascii=False)}
    ```

**Chain of Thought for Correction (Follow these steps meticulously):**

**Step 1: Reconstruct Full Sentences & Understand Scene Context**
a.  Stitch together fragmented blocks to form complete sentences.
b.  Crucially, analyze the surrounding dialogue to understand the full situation, character intent, and any unstated objects or ideas being discussed. **Infer and complete any context that a native speaker would understand even if it's missing from the spoken text.** (e.g., completing the phrase "previously on..." or identifying the subject of a fragmented sentence).

**Step 2: Diagnose the Full Sentence Holistically (Your QC Checklist)**
a.  For each complete sentence, use this enhanced **QC Checklist**.
b.  **Your QC Checklist (Revised for V6):**
    *   **`Naturalness & Conversational Tone` (Highest Priority):** Does this sound like a native speaker talking? **Avoid archaic, overly orthodox, or biblical phrasing.** Translation **MUST** use the contemporary, spoken register of the **{target_language_name}**. Replace strictly literal phrases (e.g., "I love you") with the most natural, idiomatic, and non-literal equivalent used in daily speech.
    *   **`Relational & Honorific Accuracy` (CRITICAL):** Have you correctly applied the required level of respect (formal vs. informal, e.g., 'तुम' vs 'आप' or similar) based on the inferred relationship? Have you used the correct familial terms (e.g., maternal vs. paternal grandfather)?
    *   **`Gender & Inflectional Accuracy` (CRITICAL):** Are all verbs, adjectives, and pronouns correctly inflected (conjugated) to agree with the gender, number, and formality of the speaker and listener in the **{target_language_name}**?
    *   **`Contextual & Inferential Accuracy` (CRITICAL):** Does the translation capture the *unspoken meaning*? Is it reacting only to the literal words, or to the character's full intent?
    *   **`Transliteration Policy Adherence`**: Have all **{source_language_name}** proper nouns been correctly transliterated into the **{target_language_name}** script as per Critical Rule #1?
    *   **`Semantic Divergence`:** Is the core meaning lost, changed, or twisted?

**Step 3: Synthesize the Corrected Translation**
a.  Based on your diagnosis, construct a new, perfect `corrected_translation` for the entire sentence, resolving ALL identified issues. This version should be both contextually accurate and sound perfectly natural.

**Step 4: Deconstruct, Map Back, and Apply Intelligent Line Breaks**
a.  Take your perfected, full-sentence translation from Step 3.
b.  Carefully map this corrected text back onto the original subtitle blocks it corresponds to.
c.  **Intelligent Line Breaking Rules (`\\n`):** Apply professional subtitling standards for readability within each block.
    i.   **Evaluate Necessity:** A break is needed if text exceeds **~42 characters** or if the source had a break and the corrected text is still substantially long.
    ii.  **Find the Optimal Break Point:** Prefer breaking after punctuation (commas) or before conjunctions/prepositions. Avoid breaking names.
    iii. **Ensure Visual Balance:** Avoid very short "orphaned" lines. Strive for balanced line lengths. The primary goal is readability.
    iv. **Single Break per Block:** Use a maximum of one `\\n` per block, placed at the most logical and readable point.

**Step 5: Final Assembly**
a.  For each block, create a final JSON object with the keys: `number`, `source_text`, `initial_translation`, and your final `corrected_translation`.
b.  Assemble ALL of these objects into **ONE SINGLE JSON ARRAY**.

---
**Output Format and Advanced Process Example**

First, here is the strict JSON structure for your output:
{example_output_json_structure}

Second, here is a detailed example of the advanced thought process you must use:
{example_entry_explanation}

---

Now, apply this advanced, context-driven, language-agnostic methodology to the provided data and generate the **single, complete, and impeccably corrected** JSON output.
"""
    return prompt


def generate_master_correction_prompt_v7(
        source_language_name,
        target_language_name,
        source_batch_str,
        translation_batch_str,
        character_data_str
):
    """
    Builds AIQC_V7: translation QC with transliteration consistency as highest priority.

    Purpose:
        Adds CRITICAL instruction on transliteration consistency to eliminate "Incorrect Asset"
        errors from misspelled or inconsistent proper nouns (names, brands, places).

    Args:
        source_language_name: str — Source language.
        target_language_name: str — Target language.
        source_batch_str: str | dict — Source subtitle blocks.
        translation_batch_str: str | dict — Initial translation blocks to correct.
        character_data_str: str — Character names/relationships for context.

    Returns:
        str: The full AIQC prompt for the LLM.

    Side effects / Errors:
        None. Mutates batch args in-place if they are dicts with "transcripts".
    """
    if isinstance(source_batch_str, dict) and 'transcripts' in source_batch_str:
        source_batch_str = source_batch_str['transcripts']
    if isinstance(translation_batch_str, dict) and 'transcripts' in translation_batch_str:
        translation_batch_str = translation_batch_str['transcripts']

    example_output_json_structure = """```json
[
  {
    "number": "[Original Subtitle Number]",
    "source_text": "[The original text from the Source Subtitles]",
    "initial_translation": "[The original, uncorrected text from the Initial Translation]",
    "corrected_translation": "[Your final, context-aware, fluently-phrased, and correctly formatted translation]"
  },
  // ... (repeat for ALL subtitle blocks)
]
```"""

    # This example remains the same, as its purpose is to show the workflow.
    example_entry_explanation = f"""
    **Illustrative Example of the Full Workflow**

    **NOTE:** The following detailed example uses **English-to-Hindi** for demonstration purposes ONLY. You **MUST** apply the same *principles and logical steps* to the **{source_language_name}-to-{target_language_name}** task you have been given.

    *   **Source Subtitles (Blocks 17 & 18):**
        `Subtitles:[{{'number': 17, 'text': 'This shit makes everything delicious.'}}, {{'number': 18, 'text': "Oh, shit. I have Addies\\nif you wanna be skinny tweakers."}}]`

    *   **Initial Translation (Blocks 17 & 18):**
        `Subtitles:[{{'number': 17, 'text': 'ये सब कुछ टेस्टी बना देता है।'}}, {{'number': 18, 'text': 'ओ, यार। मेरे पास Addies भी हैं,\\nअगर पतला होना है तो।'}}]`

    **Your Internal Thought Process (Applying the Chain of Thought):**

    1.  **Reconstruct:** The full thought is "This shit makes everything delicious. Oh, shit. I have Addies if you wanna be skinny tweakers."

    2.  **Diagnose (Using the QC Checklist):**
        *   **Block 17:** `Naturalness & Conversational Tone` - "ये सब कुछ टेस्टी बना देता है" is a bit literal. "This shit" is colloquially translated better as "ये चीज़" and "delicious" as "मज़ेदार".
        *   **Block 18:** `Transliteration & Consistency` - "Addies" must be transliterated and maintained consistently. `Contextual & Inferential Accuracy` - "skinny tweakers" implies not just being thin, but also being "high" or hyper, a key nuance the initial translation misses.
        *   **Relational & Honorific Accuracy:** *Check: The tone is casual/informal, so informal pronouns and verb conjugations are correct.*
        *   **Gender & Inflectional Accuracy:** *Check: No inflectional errors here.*

    3.  **Synthesize (Holistic Correction for Natural Flow):** I will rewrite both parts to be fluent, natural, and policy-compliant.
        *   *Perfected Sentence 1:* "ये चीज़ सब कुछ मज़ेदार बना देती है।"
        *   *Perfected Sentence 2:* "ओह, मेरे पास एड्डीज़ भी हैं, अगर पतला और हाइपर रहना है तो।" (This version adds the missing "hyper" context and fixes the transliteration).

    4.  **Deconstruct & Apply Intelligent Line Breaks:** Now I will map my perfect sentences back to the original blocks and apply line break rules individually.
        *   **Map to Block 17:** The corrected text is "ये चीज़ सब कुछ मज़ेदार बना देती है।".
        *   **Line Break Logic for 17:** This corrected sentence is short and well under the ~42 character limit. **No line break is needed.**
        *   **Final text for block 17:** "ये चीज़ सब कुछ मज़ेदार बना देती है।"
        *   **Map to Block 18:** The corrected text is "ओह, मेरे पास एड्डीज़ भी हैं, अगर पतला और हाइपर रहना है तो।".
        *   **Line Break Logic for 18:** This corrected sentence is now longer and exceeds the readability limit for a single line. The source also had a break. I will **add a line break** at a logical point. The comma after "हैं" is a natural clause separator and a perfect place for the break.
        *   **Final text for block 18:** "ओह, मेरे पास एड्डीज़ भी हैं,\\nअगर पतला और हाइपर रहना है तो।"

    **Expected Output Snippet (JSON for Blocks 17 & 18):**
   ```json
    [
      // ... (other blocks)
      {{
        "number": "17",
        "source_text": "This shit makes everything delicious.",
        "initial_translation": "ये सब कुछ टेस्टी बना देता है।",
        "corrected_translation": "ये चीज़ सब कुछ मज़ेदार बना देती है।"
      }},
      {{
        "number": "18",
        "source_text": "Oh, shit. I have Addies\\nif you wanna be skinny tweakers.",
        "initial_translation": "ओ, यार। मेरे पास Addies भी हैं,\\nअगर पतला होना है तो।",
        "corrected_translation": "ओह, मेरे पास एड्डीज़ भी हैं,\\nअगर पतला और हाइपर रहना है तो।"
      }}
      // ... (and so on)
    ]
    ```
    *Notice in this new example:*
    1.  The line break was **omitted** from Block 17 because the final text was short and readable.
    2.  The line break was **intelligently added** to Block 18 because the final text was long and needed it for readability.
    3.  This demonstrates that you must evaluate the need for a line break based on the **final corrected text**, not just the source formatting.
    """

    prompt = f"""
You are an expert-level, language-agnostic Subtitle Localization and Quality Control (QC) Specialist. You are a master of both **{source_language_name}** and **{target_language_name}**. Your task is to elevate an AI translation to human-mastery level by applying a universal set of principles for quality. You must focus on three core areas beyond basic fluency: 1) Deep Contextual Inference, 2) Strict Transliteration Policy, and 3) Perfect Orthographic Precision.

Your **ENTIRE RESPONSE MUST BE A SINGLE, VALID JSON ARRAY**.

**Core Methodology: Think, Don't Just Translate**
Your primary directive is to understand the *unspoken context* of the scene and ensure the translation reflects that reality. You must correct translations that are literally correct but contextually wrong. You will rigorously apply the rules and checklist below.

**CRITICAL INFERENCE CHECK (Respect & Relationship):** Before translating, you **MUST** infer the relationship between the speaker and the listener/subject (e.g., child-to-parent, formal business, romantic, maternal vs. paternal relative). This inference **MUST** dictate the choice of pronouns, honorifics, and specific familial terms in the **{target_language_name}**.

{character_data_str}

---
**CRITICAL RULE: Transliteration of All Proper Nouns & Brands**

1.  **Transliterate Proper Nouns into the Target Script:** This is a non-negotiable directive. All proper nouns (names, brands, places) from the source MUST be phonetically represented using the native alphabet of the **{target_language_name}**. Do not leave them in the source script.
    *   **ILLUSTRATION OF THE PRINCIPLE:** For English-to-Hindi, "Paula" becomes "पॉला". For English-to-Japanese, "Paula" would become "ポーラ". You must perform the correct transliteration for the specified **{target_language_name}**.

2.  **Final Output Must ONLY Contain the Target Language:** The `corrected_translation` field must be entirely in **{target_language_name}**, with the only exception being globally recognized initialisms (e.g., "NASA"). Do not mix scripts.

---

**Input Data:**

1.  **Source Subtitles (Ground Truth for Meaning and Context):**
    ```
    {json.dumps(source_batch_str, indent=2, ensure_ascii=False)}
    ```

2.  **Initial Translation (To Be Corrected):**
    ```
    {json.dumps(translation_batch_str, indent=2, ensure_ascii=False)}
    ```

**Chain of Thought for Correction (Follow these steps meticulously):**

**Step 1: Reconstruct Full Sentences & Understand Scene Context**
a.  Stitch together fragmented blocks to form complete sentences.
b.  Crucially, analyze the surrounding dialogue to understand the full situation, character intent, and any unstated objects or ideas being discussed. **Infer and complete any context that a native speaker would understand even if it's missing from the spoken text.** (e.g., completing the phrase "previously on..." or identifying the subject of a fragmented sentence).

**Step 2: Diagnose the Full Sentence Holistically (Your QC Checklist)**
a.  For each complete sentence, use this enhanced **QC Checklist**.
b.  **Your QC Checklist:**
    *   **`Transliteration & Consistency` (HIGHEST PRIORITY):** Have all proper nouns (names, brands, specific terms like 'Kryptonite') been rendered with the **correct, standardized phonetic spelling** in the **{target_language_name}** script? **Consistency is mandatory:** The spelling of any proper noun must be identical every time it appears in your corrections.
    *   **`Naturalness & Conversational Tone` (High Priority):** Does this sound like a native speaker talking? **Avoid archaic, overly orthodox, or biblical phrasing.** Translation **MUST** use the contemporary, spoken register of the **{target_language_name}**. Replace strictly literal phrases (e.g., "I love you") with the most natural, idiomatic, and non-literal equivalent used in daily speech.
    *   **`Relational & Honorific Accuracy` (CRITICAL):** Have you correctly applied the required level of respect (formal vs. informal, e.g., 'तुम' vs 'आप' or similar) based on the inferred relationship? Have you used the correct familial terms (e.g., maternal vs. paternal grandfather)?
    *   **`Gender & Inflectional Accuracy` (CRITICAL):** Are all verbs, adjectives, and pronouns correctly inflected (conjugated) to agree with the gender, number, and formality of the speaker and listener in the **{target_language_name}**?
    *   **`Contextual & Inferential Accuracy` (CRITICAL):** Does the translation capture the *unspoken meaning*? Is it reacting only to the literal words, or to the character's full intent?
    *   **`Semantic Divergence`:** Is the core meaning lost, changed, or twisted?

**Step 3: Synthesize the Corrected Translation**
a.  Based on your diagnosis, construct a new, perfect `corrected_translation` for the entire sentence, resolving ALL identified issues. This version should be both contextually accurate and sound perfectly natural.

**Step 4: Deconstruct, Map Back, and Apply Intelligent Line Breaks**
a.  Take your perfected, full-sentence translation from Step 3.
b.  Carefully map this corrected text back onto the original subtitle blocks it corresponds to.
c.  **Intelligent Line Breaking Rules (`\\n`):** Apply professional subtitling standards for readability within each block.
    i.   **Evaluate Necessity:** A break is needed if text exceeds **~42 characters** or if the source had a break and the corrected text is still substantially long.
    ii.  **Find the Optimal Break Point:** Prefer breaking after punctuation (commas) or before conjunctions/prepositions. Avoid breaking names.
    iii. **Ensure Visual Balance:** Avoid very short "orphaned" lines. Strive for balanced line lengths. The primary goal is readability.
    iv. **Single Break per Block:** Use a maximum of one `\\n` per block, placed at the most logical and readable point.

**Step 5: Final Assembly**
a.  For each block, create a final JSON object with the keys: `number`, `source_text`, `initial_translation`, and your final `corrected_translation`.
b.  Assemble ALL of these objects into **ONE SINGLE JSON ARRAY**.

---
**Output Format and Advanced Process Example**

First, here is the strict JSON structure for your output:
{example_output_json_structure}

Second, here is a detailed example of the advanced thought process you must use:
{example_entry_explanation}

---

Now, apply this advanced, context-driven, language-agnostic methodology to the provided data and generate the **single, complete, and impeccably corrected** JSON output.
"""
    return prompt


def generate_master_correction_prompt_v8(
        source_language_name,
        target_language_name,
        source_batch_str,
        translation_batch_str,
        character_data_str
):
    """
    Builds AIQC_V8: translation QC with mandatory use of provided character spellings.

    Purpose:
        Emphasizes using spellings from character_data_str for proper nouns. Fallback to
        phonetic transliteration only when a term is not in the character table.

    Args:
        source_language_name: str — Source language.
        target_language_name: str — Target language.
        source_batch_str: str | dict — Source subtitle blocks.
        translation_batch_str: str | dict — Initial translation blocks to correct.
        character_data_str: str — Character names/relationships/spellings (use provided spellings).

    Returns:
        str: The full AIQC prompt for the LLM.

    Side effects / Errors:
        None. Mutates batch args in-place if they are dicts with "transcripts".
    """
    if isinstance(source_batch_str, dict) and 'transcripts' in source_batch_str:
        source_batch_str = source_batch_str['transcripts']
    if isinstance(translation_batch_str, dict) and 'transcripts' in translation_batch_str:
        translation_batch_str = translation_batch_str['transcripts']

    example_output_json_structure = """```json
[
  {
    "number": "[Original Subtitle Number]",
    "source_text": "[The original text from the Source Subtitles]",
    "initial_translation": "[The original, uncorrected text from the Initial Translation]",
    "corrected_translation": "[Your final, context-aware, fluently-phrased, and correctly formatted translation]"
  },
  // ... (repeat for ALL subtitle blocks)
]
```"""

    # This example remains the same, as its purpose is to show the workflow.
    example_entry_explanation = f"""
    **Illustrative Example of the Full Workflow**

    **NOTE:** The following detailed example uses **English-to-Hindi** for demonstration purposes ONLY. You **MUST** apply the same *principles and logical steps* to the **{source_language_name}-to-{target_language_name}** task you have been given.

    *   **Source Subtitles (Blocks 17 & 18):**
        `Subtitles:[{{'number': 17, 'text': 'This shit makes everything delicious.'}}, {{'number': 18, 'text': "Oh, shit. I have Addies\\nif you wanna be skinny tweakers."}}]`

    *   **Initial Translation (Blocks 17 & 18):**
        `Subtitles:[{{'number': 17, 'text': 'ये सब कुछ टेस्टी बना देता है।'}}, {{'number': 18, 'text': 'ओ, यार। मेरे पास Addies भी हैं,\\nअगर पतला होना है तो।'}}]`

    **Your Internal Thought Process (Applying the Chain of Thought):**

    1.  **Reconstruct:** The full thought is "This shit makes everything delicious. Oh, shit. I have Addies if you wanna be skinny tweakers."

    2.  **Diagnose (Using the QC Checklist):**
        *   **Block 17:** `Naturalness & Conversational Tone` - "ये सब कुछ टेस्टी बना देता है" is a bit literal. "This shit" is colloquially translated better as "ये चीज़" and "delicious" as "मज़ेदार".
        *   **Block 18:** `Transliteration Policy Adherence` - "Addies" must be transliterated. *I check the Character Data (not shown here) and see 'Addies' is not a character name, so I use phonetic transliteration: 'एड्डीज़'.* `Contextual & Inferential Accuracy` - "skinny tweakers" implies not just being thin, but also being "high" or hyper, a key nuance the initial translation misses.
        *   **Relational & Honorific Accuracy:** *Check: The tone is casual/informal, so informal pronouns and verb conjugations are correct.*
        *   **Gender & Inflectional Accuracy:** *Check: No inflectional errors here.*

    3.  **Synthesize (Holistic Correction for Natural Flow):** I will rewrite both parts to be fluent, natural, and policy-compliant.
        *   *Perfected Sentence 1:* "ये चीज़ सब कुछ मज़ेदार बना देती है।"
        *   *Perfected Sentence 2:* "ओह, मेरे पास एड्डीज़ भी हैं, अगर पतला और हाइपर रहना है तो।" (This version adds the missing "hyper" context and fixes the transliteration).

    4.  **Deconstruct & Apply Intelligent Line Breaks:** Now I will map my perfect sentences back to the original blocks and apply line break rules individually.
        *   **Map to Block 17:** The corrected text is "ये चीज़ सब कुछ मज़ेदार बना देती है।".
        *   **Line Break Logic for 17:** This corrected sentence is short and well under the ~42 character limit. **No line break is needed.**
        *   **Final text for block 17:** "ये चीज़ सब कुछ मज़ेदार बना देती है।"
        *   **Map to Block 18:** The corrected text is "ओह, मेरे पास एड्डीज़ भी हैं, अगर पतला और हाइपर रहना है तो।".
        *   **Line Break Logic for 18:** This corrected sentence is now longer and exceeds the readability limit for a single line. The source also had a break. I will **add a line break** at a logical point. The comma after "हैं" is a natural clause separator and a perfect place for the break.
        *   **Final text for block 18:** "ओह, मेरे पास एड्डीज़ भी हैं,\\nअगर पतला और हाइपर रहना है तो।"

    **Expected Output Snippet (JSON for Blocks 17 & 18):**
   ```json
    [
      // ... (other blocks)
      {{
        "number": "17",
        "source_text": "This shit makes everything delicious.",
        "initial_translation": "ये सब कुछ टेस्टी बना देता है।",
        "corrected_translation": "ये चीज़ सब कुछ मज़ेदार बना देती है।"
      }},
      {{
        "number": "18",
        "source_text": "Oh, shit. I have Addies\\nif you wanna be skinny tweakers.",
        "initial_translation": "ओ, यार। मेरे पास Addies भी हैं,\\nअगर पतला होना है तो।",
        "corrected_translation": "ओह, मेरे पास एड्डीज़ भी हैं,\\nअगर पतला और हाइपर रहना है तो।"
      }}
      // ... (and so on)
    ]
    ```
    *Notice in this new example:*
    1.  The line break was **omitted** from Block 17 because the final text was short and readable.
    2.  The line break was **intelligently added** to Block 18 because the final text was long and needed it for readability.
    3.  This demonstrates that you must evaluate the need for a line break based on the **final corrected text**, not just the source formatting.
    """

    arabic_rule = ""
    if target_language_name.lower() == "arabic":
        arabic_rule = "\n\n4.  **Arabic Dialect Restriction:** When translating to Arabic, you MUST use Modern Standard Arabic (MSA) only. Do NOT use Saudi dialect, Egyptian dialect, or any other regional dialect. All translations must be in standard Arabic dialect that is universally understood across all Arabic-speaking regions. All numbers must be written using standard English digits (1, 2, 3) — not Arabic-Indic digits (١، ٢، ٣)."

    prompt = f"""
You are an expert-level, language-agnostic Subtitle Localization and Quality Control (QC) Specialist. You are a master of both **{source_language_name}** and **{target_language_name}**. Your task is to elevate an AI translation to human-mastery level by applying a universal set of principles for quality. You must focus on three core areas beyond basic fluency: 1) Deep Contextual Inference, 2) Strict Transliteration Policy, and 3) Perfect Orthographic Precision.

Your **ENTIRE RESPONSE MUST BE A SINGLE, VALID JSON ARRAY**.

**Core Methodology: Think, Don't Just Translate**
Your primary directive is to understand the *unspoken context* of the scene and ensure the translation reflects that reality. You must correct translations that are literally correct but contextually wrong. You will rigorously apply the rules and checklist below.

**CRITICAL INFERENCE CHECK (Respect & Relationship):** Before translating, you **MUST** infer the relationship between the speaker and the listener/subject (e.g., child-to-parent, formal business, romantic, maternal vs. paternal relative). This inference **MUST** dictate the choice of pronouns, honorifics, and specific familial terms in the **{target_language_name}**.

{character_data_str}

---
**CRITICAL RULE: Transliteration of All Proper Nouns & Brands**

1.  **Use Provided Character Spellings (CRITICAL):** If a proper noun (character name, etc.) appears in the 'Translated Name' column of the provided `character_data_str`, you **MUST** use that specific spelling in the final corrected translation for absolute consistency within the series.

2.  **Fallback Transliteration into the Target Script:** If a proper noun is **NOT** listed in the `character_data_str`, it must be phonetically represented using the native alphabet of the **{target_language_name}**. Do not leave it in the source script.
    *   **ILLUSTRATION OF THE PRINCIPLE:** For English-to-Hindi, "Paula" becomes "पॉला". For English-to-Japanese, "Paula" would become "ポーラ". You must perform the correct transliteration for the specified **{target_language_name}**.

3.  **Final Output Must ONLY Contain the Target Language:** The `corrected_translation` field must be entirely in **{target_language_name}**, with the only exception being globally recognized initialisms (e.g., "NASA"). Do not mix scripts.{arabic_rule}

---

**Input Data:**
***The input text may include copyrighted material. I am processing it under licensed usage within my organization.***

1.  **Source Subtitles (Ground Truth for Meaning and Context):**
    ```
    {json.dumps(source_batch_str, indent=2, ensure_ascii=False)}
    ```

2.  **Initial Translation (To Be Corrected):**
    ```
    {json.dumps(translation_batch_str, indent=2, ensure_ascii=False)}
    ```

**Chain of Thought for Correction (Follow these steps meticulously):**

**Step 1: Reconstruct Full Sentences & Understand Scene Context**
a.  Stitch together fragmented blocks to form complete sentences.
b.  Crucially, analyze the surrounding dialogue to understand the full situation, character intent, and any unstated objects or ideas being discussed. **Infer and complete any context that a native speaker would understand even if it's missing from the spoken text.** (e.g., completing the phrase "previously on..." or identifying the subject of a fragmented sentence).

**Step 2: Diagnose the Full Sentence Holistically (Your QC Checklist)**
a.  For each complete sentence, use this enhanced **QC Checklist**.
b.  **Your QC Checklist (Revised for V7):**
    *   **`Naturalness & Conversational Tone` (Highest Priority):** Does this sound like a native speaker talking? **Avoid archaic, overly orthodox, or biblical phrasing.** Translation **MUST** use the contemporary, spoken register of the **{target_language_name}**. Replace strictly literal phrases (e.g., "I love you") with the most natural, idiomatic, and non-literal equivalent used in daily speech.
    *   **`Relational & Honorific Accuracy` (CRITICAL):** Have you correctly applied the required level of respect (formal vs. informal, e.g., 'तुम' vs 'आप' or similar) based on the inferred relationship? Have you used the correct familial terms (e.g., maternal vs. paternal grandfather)?
    *   **`Gender & Inflectional Accuracy` (CRITICAL):** Are all verbs, adjectives, and pronouns correctly inflected (conjugated) to agree with the gender, number, and formality of the speaker and listener in the **{target_language_name}**?
    *   **`Contextual & Inferential Accuracy` (CRITICAL):** Does the translation capture the *unspoken meaning*? Is it reacting only to the literal words, or to the character's full intent?
    *   **`Transliteration Policy Adherence`**: Have all proper nouns been correctly spelled according to **Critical Rule #1 (Provided Spellings)** or **Rule #2 (Fallback Phonetic Transliteration)**?
    *   **`Semantic Divergence`:** Is the core meaning lost, changed, or twisted?

**Step 3: Synthesize the Corrected Translation**
a.  Based on your diagnosis, construct a new, perfect `corrected_translation` for the entire sentence, resolving ALL identified issues. This version should be both contextually accurate and sound perfectly natural.

**Step 4: Deconstruct, Map Back, and Apply Intelligent Line Breaks**
a.  Take your perfected, full-sentence translation from Step 3.
b.  Carefully map this corrected text back onto the original subtitle blocks it corresponds to.
c.  **Intelligent Line Breaking Rules (`\\n`):** Apply professional subtitling standards for readability within each block.
    i.   **Evaluate Necessity:** A break is needed if text exceeds **~42 characters** or if the source had a break and the corrected text is still substantially long.
    ii.  **Find the Optimal Break Point:** Prefer breaking after punctuation (commas) or before conjunctions/prepositions. Avoid breaking names.
    iii. **Ensure Visual Balance:** Avoid very short "orphaned" lines. Strive for balanced line lengths. The primary goal is readability.
    iv. **Single Break per Block:** Use a maximum of one `\\n` per block, placed at the most logical and readable point.

**Step 5: Final Assembly**
a.  For each block, create a final JSON object with the keys: `number`, `source_text`, `initial_translation`, and your final `corrected_translation`.
b.  Assemble ALL of these objects into **ONE SINGLE JSON ARRAY**.

---
**Output Format and Advanced Process Example**

First, here is the strict JSON structure for your output:
{example_output_json_structure}

Second, here is a detailed example of the advanced thought process you must use:
{example_entry_explanation}

---

Now, apply this advanced, context-driven, language-agnostic methodology to the provided data and generate the **single, complete, and impeccably corrected** JSON output.
"""
    return prompt


# ======================================================================
# LLM Translation prompts (from llmTranslationHelper)
# ======================================================================

def generate_llm_translation_prompt_old(batches_data, input_language, output_language):
    """
    Builds a translation prompt for subtitles (legacy, no script context).

    Purpose:
        Produces a prompt for LLM translation of subtitle batches with holistic understanding
        and sentence-level segmentation. Does not include script context.

    Args:
        batches_data: list — Batch of subtitle dicts (e.g., with "transcripts" key).
        input_language: str — Source language of the subtitles.
        output_language: str — Target language for translation.

    Returns:
        str: The full prompt string for the LLM.

    Side effects / Errors:
        None. Converts batches_data to JSON internally.
    """
    batches_data = json.dumps(batches_data)
    default_prompt = f"""
    You are a highly skilled and meticulous subtitle translator with expertise in translating between various languages while maintaining accuracy, cultural nuance, and natural-sounding dialogue. You meticulously adhere to established subtitle guidelines and best practices and prioritize understanding the full context of a scene before translating individual subtitles.

    **Task:**  Translate the provided batch of subtitles from **{input_language}** to **{output_language}**, strictly adhering to professional subtitling conventions.  Pay special attention to sentence continuity across multiple subtitle entries.

    **Input Subtitles (JSON Array - Batch of subtitles):**

    {batches_data}

    **Instructions:**

    Instructions:

    1️⃣ Holistic Understanding:
    🔸 Before translating individual subtitles, carefully read all transcripts within the provided batch to grasp the overall context, storyline, character interactions, and any ongoing conversations.
    🔸 Identify Key Elements: Identify key nouns, pronouns, proper nouns, objects, places, and other relevant elements in {input_language} to ensure they remain unchanged for accurate and consistent translation.
    🔸 Identify complete sentences that may span multiple subtitle entries.

    2️⃣ Sentence-Level Translation and Segmentation (CRITICAL):
    🔸 Translate the entire sentence as a whole, even if it spans multiple subtitle entries. Ensure the complete meaning is conveyed in the Simplification Focused translation. Use simple, conversational {output_language}. Avoid formal or complex vocabulary unless necessary.
    🔸 After translating the full sentence, segment the translated text to fit the original subtitle breaks. Ensure that each segment maintains the flow and meaning of the complete sentence, aligning with the original subtitle timing.
    🔸 Sentence Continuity Focus: Ensure that the translation of sentences spanning multiple subtitles maintains the flow and meaning across all relevant subtitle entries.

    3️⃣ Adhere to Subtitle Guidelines: 

        🔸 Accuracy and Clarity: Convey the precise meaning and tone in clear, natural-sounding {output_language}. Avoid literal translations. Provide concise, conversational translations. Do not add descriptions or interpretations.
        🔸 Grammar and Spelling: Ensure impeccable grammar and spelling in {output_language}.
        🔸 Conciseness: Keep subtitles concise without omitting crucial information.
        🔸 Punctuation and Quotes:
        * Single Quotes ('...'): Dialogues, internal monologues, voiceovers, quotes, poems, mantras, flashbacks/recaps.
        * Double Quotes ("..."): Song lyrics only (use ?, ! within lyrics, not , or .). Capitalize each line of a song.
        🔸 Dialogue Separation: Separate multiple speakers' dialogues within a single entry with a hyphen (-).
        🔸 Incomplete Sentences: Use an ellipsis (...) for incomplete sentences. If the next entry continues the thought, begin that sentence with a capital letter.
        🔸 Cultural Adaptation: Adapt culturally specific terms/phrases for the {output_language} audience while maintaining the original meaning. Use single quotes if no direct equivalent exists.

    4️⃣ Output in JSON Dict (Final, Verified Translations): Provide your final, verified output in JSON format, ensuring accurate subtitle segmentation:

    ```json
            [
                "number": "[Original Subtitle Number]",
                "text": "[Original Text]",
                "translated_text": "[Your Translated Text in {output_language}]",

                "number": "[Original Subtitle Number]",
                "text": "[Original Text]",
                "translated_text": "[Your Translated Text in {output_language}]",
              // ... (rest of the translated subtitles)
            ]
    ```
    """
    return default_prompt


def generate_llm_translation_prompt(srt_transcript_batch_data, script_batch_data, input_language, output_language):
    """
    Builds a translation prompt with script context for character/gender verification.

    Purpose:
        Produces a prompt for LLM translation of subtitles with aligned script context for
        accurate character, gender, and relationship handling in the target language.

    Args:
        srt_transcript_batch_data: list — Primary subtitle batch to translate.
        script_batch_data: list — Aligned script context (speaker, dialogue) for verification.
        input_language: str — Source language.
        output_language: str — Target language.

    Returns:
        str: The full prompt string for the LLM.

    Side effects / Errors:
        None.
    """
    # Dump both data sets to JSON strings
    srt_batch_json = json.dumps(srt_transcript_batch_data)
    script_context_json = json.dumps(script_batch_data)

    default_prompt = f"""
    You are a highly skilled and meticulous subtitle translator with expertise in translating between various languages while maintaining accuracy, cultural nuance, and natural-sounding dialogue. You strictly adhere to professional subtitling conventions.

    **Task:**  Translate the provided batch of subtitles from **{input_language}** to **{output_language}**, utilizing the accompanying **Script Context** for verification of character, gender, and relationship, and strictly adhering to professional subtitling conventions.

    **Primary Input Subtitles (JSON Array):**
    *   This is the text to be translated and segmented according to its line numbers.

    {srt_batch_json}

    **Script Context (JSON Array):**
    *   This data provides the original, authoritative speaker name and the exact dialogue line from the script source, matching the primary input lines by index. **USE THIS FOR CONTEXT AND CHARACTER VERIFICATION.**

    {script_context_json}

    **Instructions:**

    1️⃣ Contextual and Conversational Translation (CRITICAL):
    🔸 **Use the 'speaker' tag from the Script Context** to verify the character (e.g., LOIS, GENERAL_LANE, JONATHAN).
    🔸 **Character and Gender Verification:** Ensure all pronouns, honorifics, and relational terms (like 'Dad', 'Grandpa', 'sweetie') in the **{output_language}** translation correctly reflect the speaker's and the addressed character's **gender and relationship** (e.g., Lois to Clark, or Jordan to General Lane).
    🔸 **Tone and Style:** The translated text must be **conversational, modern, and suitable for contemporary subtitles**. You must avoid **literal, archaic, Biblical, or overly formal vocabulary** unless explicitly required by the character's persona (which is generally casual for a family drama like 'Superman & Lois').

    2️⃣ Quality Control and Refinement (CRITICAL):
    🔸 **Correct All Errors:** You must meticulously check and **correct any incorrect spelling, verb conjugation, grammatical errors, or awkward phrasing** that may result from initial literal translation attempts. The final **{output_language}** quality must be impeccable.
    🔸 **Holistic Understanding:** Read the full batch of dialogue and the context to translate complete sentences spanning multiple subtitle entries.

    3️⃣ Subtitle Guidelines: 
    🔸 **Accuracy:** Convey the precise meaning and tone. Avoid adding descriptions or interpretations.
    🔸 **Conciseness:** Keep subtitles concise.
    🔸 **Punctuation:** Use single quotes ('...') for dialogue, voiceovers, quotes, etc. Use double quotes ("...") for song lyrics only.
    🔸 **Dialogue Separation:** Separate multiple speakers' dialogues within a single entry with a hyphen (-).
    🔸 **Incomplete Sentences:** Use an ellipsis (...) for incomplete sentences.

    4️⃣ Output in JSON Array (Final, Verified Translations): Provide your final, verified output in the exact same structure as the primary input, containing **only** the translated text. Do not include the script context data in the final output.

    ```json
            [
                {{"number": "[Original Subtitle Number]", "text": "[Original Text]", "translated_text": "[Your Translated Text in {output_language}]"}},
              // ... (rest of the translated subtitles)
            ]
    ```
    """
    return default_prompt


def generate_llm_translation_prompt_v2(srt_transcript_batch_data, script_batch_data, input_language, output_language):
    """
    Builds a translation prompt with script context and conversational-tone emphasis.

    Purpose:
        Same as generate_llm_translation_prompt but adds explicit instruction to prioritize
        contemporary, conversational tone and avoid archaic/orthodox vocabulary.

    Args:
        srt_transcript_batch_data: list — Primary subtitle batch to translate.
        script_batch_data: list — Aligned script context for character verification.
        input_language: str — Source language.
        output_language: str — Target language.

    Returns:
        str: The full prompt string for the LLM.

    Side effects / Errors:
        None.
    """
    # Dump both data sets to JSON strings
    srt_batch_json = json.dumps(srt_transcript_batch_data, ensure_ascii=False, indent=4)
    script_context_json = json.dumps(script_batch_data, ensure_ascii=False, indent=4)

    default_prompt = f"""
    You are a highly skilled and meticulous subtitle translator with expertise in translating between various languages while maintaining accuracy, cultural nuance, and natural-sounding dialogue. You strictly adhere to professional subtitling conventions.

    **Task:** Translate the provided batch of subtitles from **{input_language}** to **{output_language}**, utilizing the accompanying **Script Context** for verification of character, gender, and relationship, and strictly adhering to professional subtitling conventions.

    **Primary Input Subtitles (JSON Array):**
    *   This is the text to be translated and segmented according to its line numbers.

    {srt_batch_json}

    **Script Context (JSON Array):**
    *   This data provides the original, authoritative speaker name and the exact dialogue line from the script source, matching the primary input lines by index. **USE THIS FOR CONTEXT AND CHARACTER VERIFICATION.**

    {script_context_json}

    **Instructions:**

    1️⃣ Contextual and Conversational Translation (CRITICAL):
    🔸 **Use the 'speaker' tag from the Script Context** to verify the character (e.g., LOIS, GENERAL_LANE, JONATHAN).
    🔸 **Character and Gender Verification:** Ensure all pronouns, honorifics, and relational terms (like 'Dad', 'Grandpa', 'sweetie') in the **{output_language}** translation correctly reflect the speaker's and the addressed character's **gender and relationship** (e.g., Lois to Clark, or Jordan to General Lane).
    🔸 **Tone and Style (Highest Priority):** The translated text must be **conversational, contemporary, and suitable for daily, natural speech**. You must **strictly avoid overly literal, archaic, Biblical, or Orthodox vocabulary** unless the source character is explicitly speaking in an outdated style. The goal is a non-literal, fluent translation (e.g., translating "I love you" as the most commonly spoken, intimate expression, not the most formal, textbook version).

    2️⃣ Sentence-Level Translation and Segmentation (CRITICAL):
    🔸 **Holistic Understanding:** Read the full batch of dialogue and the context to translate complete sentences spanning multiple subtitle entries.
    🔸 **Translate the entire sentence as a whole,** even if it spans multiple subtitle entries. Ensure the complete meaning is conveyed in the translation. Use simple, conversational **{output_language}**.
    🔸 **Segmentation:** After translating the full sentence, segment the translated text to fit the original subtitle breaks. Ensure that each segment maintains the flow and meaning of the complete sentence, aligning with the original subtitle timing.

    3️⃣ Quality Control and Refinement (CRITICAL):
    🔸 **Correct All Errors:** You must meticulously check and **correct any incorrect spelling, verb conjugation, grammatical errors, or awkward phrasing** that may result from initial literal translation attempts. The final **{output_language}** quality must be impeccable.
    🔸 **Pronoun/Verb Agreement:** Ensure perfect agreement of verbs and pronouns with the gender, number, and formality level of the characters.

    4️⃣ Subtitle Guidelines: 
    🔸 **Accuracy:** Convey the precise meaning and tone. Avoid adding descriptions or interpretations.
    🔸 **Conciseness:** Keep subtitles concise.
    🔸 **Punctuation:** Use single quotes ('...') for dialogue, voiceovers, quotes, etc. Use double quotes ("...") for song lyrics only.
    🔸 **Dialogue Separation:** Separate multiple speakers' dialogues within a single entry with a hyphen (-).
    🔸 **Incomplete Sentences:** Use an ellipsis (...) for incomplete sentences.

    5️⃣ Output in JSON Array (Final, Verified Translations): Provide your final, verified output in the exact same structure as the primary input, containing **only** the translated text. Do not include the script context data in the final output.

    ```json
            [
                {{"number": "[Original Subtitle Number]", "text": "[Original Text]", "translated_text": "[Your Translated Text in {output_language}]"}},
              // ... (rest of the translated subtitles)
            ]
    ```
    """
    return default_prompt


def generate_llm_translation_prompt_v3(srt_transcript_batch_data, script_batch_data, input_language, output_language):
    """
    Builds a translation prompt with script context and transliteration consistency rules.

    Purpose:
        Same as V2 but adds CRITICAL instructions for consistent, accurate transliteration of
        proper nouns (names, brands, places) to eliminate "Incorrect Asset" errors.

    Args:
        srt_transcript_batch_data: list — Primary subtitle batch to translate.
        script_batch_data: list — Aligned script context for character verification.
        input_language: str — Source language.
        output_language: str — Target language.

    Returns:
        str: The full prompt string for the LLM.

    Side effects / Errors:
        None.
    """
    # Dump both data sets to JSON strings
    srt_batch_json = json.dumps(srt_transcript_batch_data, ensure_ascii=False, indent=4)
    script_context_json = json.dumps(script_batch_data, ensure_ascii=False, indent=4)

    default_prompt = f"""
    You are a highly skilled and meticulous subtitle translator with expertise in translating between various languages while maintaining accuracy, cultural nuance, and natural-sounding dialogue. You strictly adhere to professional subtitling conventions.

    **Task:** Translate the provided batch of subtitles from **{input_language}** to **{output_language}**, utilizing the accompanying **Script Context** for verification of character, gender, and relationship, and strictly adhering to professional subtitling conventions.

    **Primary Input Subtitles (JSON Array):**
    *   This is the text to be translated and segmented according to its line numbers.

    {srt_batch_json}

    **Script Context (JSON Array):**
    *   This data provides the original, authoritative speaker name and the exact dialogue line from the script source, matching the primary input lines by index. **USE THIS FOR CONTEXT AND CHARACTER VERIFICATION.**

    {script_context_json}

    **Instructions:**

    1️⃣ Contextual and Conversational Translation (CRITICAL):
    🔸 **Use the 'speaker' tag from the Script Context** to verify the character (e.g., LOIS, GENERAL_LANE, JONATHAN).
    🔸 **Character and Gender Verification:** Ensure all pronouns, honorifics, and relational terms (like 'Dad', 'Grandpa', 'sweetie') in the **{output_language}** translation correctly reflect the speaker's and the addressed character's **gender and relationship** (e.g., Lois to Clark, or Jordan to General Lane).
    🔸 **Tone and Style (Highest Priority):** The translated text must be **conversational, contemporary, and suitable for daily, natural speech**. You must **strictly avoid overly literal, archaic, Biblical, or Orthodox vocabulary** unless the source character is explicitly speaking in an outdated style. The goal is a non-literal, fluent translation (e.g., translating "I love you" as the most commonly spoken, intimate expression, not the most formal, textbook version).

    2️⃣ Sentence-Level Translation and Segmentation (CRITICAL):
    🔸 **Holistic Understanding:** Read the full batch of dialogue and the context to translate complete sentences spanning multiple subtitle entries.
    🔸 **Translate the entire sentence as a whole,** even if it spans multiple subtitle entries. Ensure the complete meaning is conveyed in the translation. Use simple, conversational **{output_language}**.
    🔸 **Segmentation:** After translating the full sentence, segment the translated text to fit the original subtitle breaks. Ensure that each segment maintains the flow and meaning of the complete sentence, aligning with the original subtitle timing.

    3️⃣ Transliteration & Consistency (CRITICAL):
    🔸 **Accurate Transliteration:** Every proper noun (names, brands, organizations like 'Eckworth Industries', specific items like 'Kryptonite') must be rendered using the most accurate and standard phonetic equivalent in the **{output_language}** script.
    🔸 **Absolute Consistency:** Once you choose the transliteration for a proper noun (e.g., 'Clark'), you **MUST** use that exact spelling consistently across all subtitle entries in the entire batch, even if the source is fragmented. **Never misspell a proper noun.**

    4️⃣ Quality Control and Refinement (CRITICAL):
    🔸 **Correct All Errors:** You must meticulously check and **correct any incorrect spelling, verb conjugation, grammatical errors, or awkward phrasing** that may result from initial literal translation attempts. The final **{output_language}** quality must be impeccable.
    🔸 **Pronoun/Verb Agreement:** Ensure perfect agreement of verbs and pronouns with the gender, number, and formality level of the characters.

    5️⃣ Subtitle Guidelines: 
    🔸 **Accuracy:** Convey the precise meaning and tone. Avoid adding descriptions or interpretations.
    🔸 **Conciseness:** Keep subtitles concise.
    🔸 **Punctuation:** Use single quotes ('...') for dialogue, voiceovers, quotes, etc. Use double quotes ("...") for song lyrics only.
    🔸 **Dialogue Separation:** Separate multiple speakers' dialogues within a single entry with a hyphen (-).
    🔸 **Incomplete Sentences:** Use an ellipsis (...) for incomplete sentences.

    6️⃣ Output in JSON Array (Final, Verified Translations): Provide your final, verified output in the exact same structure as the primary input, containing **only** the translated text. Do not include the script context data in the final output.

    ```json
            [
                {{"number": "[Original Subtitle Number]", "text": "[Original Text]", "translated_text": "[Your Translated Text in {output_language}]"}},
              // ... (rest of the translated subtitles)
            ]
    ```
    """
    return default_prompt


