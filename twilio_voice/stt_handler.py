"""
stt_handler.py
Speech-to-Text handler for Twilio voice calls.

Twilio does STT automatically via Gather verb.
This file handles:
  - Cleaning and validating STT output
  - Extracting registration numbers from speech
  - Handling common STT mistakes (Indian accent)
  - Confidence score filtering
  - Domain keyword corrections (fees, hostel, attendance etc.)
"""

import re
import logging

logger = logging.getLogger("helpline.stt_handler")

# Minimum confidence score to accept speech
MIN_CONFIDENCE = 0.3

# Common STT mistakes for Indian English 
STT_CORRECTIONS = {

    # NUMBER CORRECTIONS 
    "to thousand":          "2000",
    "twenty twenty":        "2020",
    "twenty twenty one":    "2021",
    "twenty twenty two":    "2022",
    "twenty twenty three":  "2023",
    "twenty twenty four":   "2024",

    # --- DEPARTMENT CODE CORRECTIONS 
    "cs":  "CS",
    "ec":  "EC",
    "ee":  "EE",
    "me":  "ME",
    "ce":  "CE",
    "it":  "IT",
    "bc":  "BC",
    "mba": "MBA",
    "bca": "BCA",
    "mca": "MCA",
    "b tech": "B.Tech",
    "btech":  "B.Tech",

    # FEES MISHEARS 
    # Student says "fees" — Twilio returns one of these
    "peace":   "fees",
    "fish":    "fees",
    "fear":    "fees",
    "feed":    "fees",
    "feets":   "fees",
    "feast":   "fees",
    "fee's":   "fees",

    # HOSTEL MISHEARS 
    # Student says "hostel" — Twilio returns one of these
    "hostile":  "hostel",
    "hostels":  "hostel",
    "hosel":    "hostel",
    "hoistelle":"hostel",

    # ATTENDANCE MISHEARS 
    # Student says "attendance" — Twilio returns one of these
    "a dance":      "attendance",
    "intendance":   "attendance",
    "attendants":   "attendance",
    "attendence":   "attendance",
    "attandance":   "attendance",

    # RESULT / MARKS MISHEARS 
    # Student says "result" or "marks" — Twilio returns one of these
    "rustle":   "results",
    "wrestle":  "results",
    "rezult":   "results",
    "parks":    "marks",
    "darks":    "marks",
    "barks":    "marks",

    # EXAM MISHEARS 
    # Student says "exam" — Twilio returns one of these
    "example":  "exam",
    "exam's":   "exam",
    "exams":    "exams",

    # SCHOLARSHIP MISHEARS 
    "scholar ship": "scholarship",
    "scholarships": "scholarship",

    # ADMISSION MISHEARS
    "admission's": "admission",
    "admissions":  "admission",

    # LIBRARY MISHEARS 
    "library's":  "library",
    "lie berry":  "library",
    "lie brary":  "library",

    # DOCUMENT MISHEARS 
    "document's": "documents",
    "dock you meant": "document",
}


def process_speech(
    speech_result: str,
    confidence: float
) -> tuple[bool, str]:
    """
    Process raw STT output from Twilio.

    Args:
        speech_result: Raw text from Twilio STT
        confidence:    Confidence score 0.0 to 1.0

    Returns:
        (True, cleaned_text)   — speech accepted
        (False, reason)        — speech rejected

    Example:
        ok, text = process_speech("show my attendance", 0.85)
        if ok:
            # send to AI
        else:
            # ask student to repeat

    Note:
        Low confidence (below MIN_CONFIDENCE) is rejected here.
        Borderline confidence (0.3–0.6) is accepted but STT corrections
        are especially important at this range — misheard words are common.
    """
    if not speech_result or not speech_result.strip():
        logger.info("[STT] Empty speech result")
        return False, "empty"

    if confidence < MIN_CONFIDENCE:
        logger.info(f"[STT] Low confidence: {confidence:.2f} — '{speech_result}'")
        return False, "low_confidence"

    cleaned = clean_speech(speech_result)
    logger.info(f"[STT] Accepted: '{cleaned}' (confidence: {confidence:.2f})")
    return True, cleaned


def clean_speech(text: str) -> str:
    """
    Clean and normalize STT output.

    - Strips extra whitespace
    - Fixes common Indian English STT mistakes
    - Fixes domain keyword mishears (fees, hostel, attendance etc.)
    - Normalizes registration number format

    Args:
        text: Raw STT text

    Returns:
        Cleaned text

    Note:
        Corrections are applied on lowercased text so matching is
        case-insensitive. Registration number fixer runs last because
        it needs to work on the already-corrected lowercase text.
    """
    text = text.strip()

    # Fix common STT mistakes — runs on lowercased text for case-insensitive match
    lower = text.lower()
    for wrong, correct in STT_CORRECTIONS.items():
        lower = lower.replace(wrong, correct)

    # Try to fix registration number if present
    text = _fix_registration_number(lower)

    return text


def _fix_registration_number(text: str) -> str:
    """
    STT often breaks registration numbers.
    E.g. "2024 E C 0 3 3" → "2024EC033"
         "twenty twenty four ec zero three three" → "2024EC033"

    Args:
        text: STT output

    Returns:
        Text with fixed registration number if found
    """
    # Pattern: 4 digits + 2 letters + 3 digits (with optional spaces)
    pattern = r'(\d{4})\s*([a-zA-Z]{2})\s*(\d{3})'
    match = re.search(pattern, text)

    if match:
        year = match.group(1)
        dept = match.group(2).upper()
        num  = match.group(3)
        reg  = f"{year}{dept}{num}"

        # Replace in original text
        text = text[:match.start()] + reg + text[match.end():]
        logger.info(f"[STT] Fixed reg number: {reg}")

    return text


def extract_registration_number(text: str) -> str | None:
    """
    Extract registration number from speech text.

    Args:
        text: Cleaned speech text

    Returns:
        Registration number string or None

    Example:
        reg = extract_registration_number("my reg is 12345678")
        # Returns "12345678"

    Note:
        Pattern matches exactly 8 digits — matching your college DB format.
        Previous pattern (1\\d{8}) was wrong — it matched 9 digits starting
        with 1, which would never match real student registration numbers.
    """
    # Fixed: 8-digit numeric registration number — matches actual DB format
    # Old pattern r'\b(1\d{8})\b' was incorrect (matched 9 digits)
    pattern = r'\b(\d{8})\b'
    match = re.search(pattern, text.upper())

    if match:
        reg = match.group(1)
        logger.info(f"[STT] Extracted reg number: {reg}")
        return reg

    return None


def extract_otp(text: str) -> str | None:
    """
    Extract 6-digit OTP from speech text.
    STT may return OTP as "1 2 3 4 5 6" or "123456".

    Args:
        text: STT output

    Returns:
        6-digit OTP string or None

    Example:
        otp = extract_otp("my otp is 1 2 3 4 5 6")
        # Returns "123456"
    """
    # Remove spaces between digits
    digits_only = re.sub(r'(\d)\s+(\d)', r'\1\2', text)
    digits_only = re.sub(r'(\d)\s+(\d)', r'\1\2', digits_only)  # second pass

    # Look for 6 consecutive digits
    match = re.search(r'\b(\d{6})\b', digits_only)
    if match:
        otp = match.group(1)
        logger.info(f"[STT] Extracted OTP: {otp}")
        return otp

    return None