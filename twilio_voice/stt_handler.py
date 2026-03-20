"""
stt_handler.py
Speech-to-Text handler for Twilio voice calls.

Twilio does STT automatically via Gather verb.
This file handles:
  - Cleaning and validating STT output
  - Extracting registration numbers from speech
  - Handling common STT mistakes (Indian accent)
  - Confidence score filtering
"""

import re
import logging

logger = logging.getLogger("helpline.stt_handler")

# Minimum confidence score to accept speech
MIN_CONFIDENCE = 0.3

# Common STT mistakes for Indian English — fix these
STT_CORRECTIONS = {
    "to thousand":    "2000",
    "twenty twenty":  "2020",
    "twenty twenty one": "2021",
    "twenty twenty two": "2022",
    "twenty twenty three": "2023",
    "twenty twenty four": "2024",
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
    "btech": "B.Tech",
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
    - Normalizes registration number format

    Args:
        text: Raw STT text

    Returns:
        Cleaned text
    """
    text = text.strip()

    # Fix common STT mistakes
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
        reg = extract_registration_number("my reg is 2024EC033")
        # Returns "2024EC033"
    """
    # Standard format: 2024EC033
    pattern = r'\b(\d{4}[A-Z]{2}\d{3})\b'
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
