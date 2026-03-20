"""
tts_handler.py
Text-to-Speech handler for Twilio voice calls.

Twilio does TTS automatically via <Say> verb.
This file handles:
  - Cleaning AI responses before speaking
  - Making text sound natural on a phone call
  - Choosing the right voice
  - Handling long responses (splitting if needed)
"""

import re
import logging

logger = logging.getLogger("helpline.tts_handler")

# Maximum characters Twilio TTS handles well in one <Say>
MAX_SAY_LENGTH = 500

# Indian English voice — sounds most natural for Indian students
DEFAULT_VOICE    = "Polly.Aditi"
DEFAULT_LANGUAGE = "en-IN"


def prepare_for_speech(text: str) -> str:
    """
    Clean AI response text so it sounds natural when spoken.

    - Removes markdown formatting
    - Expands abbreviations
    - Fixes numbers and currencies
    - Removes emojis
    - Shortens if too long

    Args:
        text: Raw AI response text

    Returns:
        Clean text ready for Twilio TTS

    Example:
        clean = prepare_for_speech("Fee: Rs.50,000. Status: **Pending**")
        # Returns "Fee is Rupees 50 thousand. Status is Pending."
    """
    if not text:
        return "I'm sorry, I couldn't generate a response."

    text = _remove_emojis(text)
    text = _remove_markdown(text)
    text = _expand_abbreviations(text)
    text = _fix_currency(text)
    text = _fix_numbers(text)
    text = _fix_punctuation(text)
    text = _truncate_if_long(text)

    return text.strip()


def _remove_emojis(text: str) -> str:
    """Remove emojis — TTS reads them as weird symbols."""
    emoji_pattern = re.compile(
        "["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        "]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub("", text)


def _remove_markdown(text: str) -> str:
    """Remove markdown — **bold**, *italic*, # headers, bullets."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)   # **bold**
    text = re.sub(r'\*(.+?)\*', r'\1', text)         # *italic*
    text = re.sub(r'#{1,6}\s', '', text)             # # headers
    text = re.sub(r'^\s*[-•*]\s', '', text, flags=re.MULTILINE)  # bullets
    text = re.sub(r'`(.+?)`', r'\1', text)           # `code`
    return text


def _expand_abbreviations(text: str) -> str:
    """Expand common college abbreviations for natural speech."""
    replacements = {
        r'\bCSE\b':  "Computer Science and Engineering",
        r'\bECE\b':  "Electronics and Communication Engineering",
        r'\bEEE\b':  "Electrical and Electronics Engineering",
        r'\bME\b':   "Mechanical Engineering",
        r'\bCE\b':   "Civil Engineering",
        r'\bIT\b':   "Information Technology",
        r'\bMBA\b':  "M B A",
        r'\bBCA\b':  "B C A",
        r'\bMCA\b':  "M C A",
        r'\bGPA\b':  "G P A",
        r'\bSGPA\b': "S G P A",
        r'\bCGPA\b': "C G P A",
        r'\bOTP\b':  "O T P",
        r'\bTC\b':   "Transfer Certificate",
        r'\bDOB\b':  "date of birth",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    return text


def _fix_currency(text: str) -> str:
    """Make currency amounts speakable."""
    # Rs.50000 → Rupees 50 thousand
    def replace_currency(match):
        amount = int(match.group(1).replace(",", ""))
        if amount >= 100000:
            lakhs = amount / 100000
            return f"Rupees {lakhs:.1f} lakhs"
        elif amount >= 1000:
            thousands = amount / 1000
            return f"Rupees {thousands:.0f} thousand"
        else:
            return f"Rupees {amount}"

    text = re.sub(r'Rs\.?\s*(\d[\d,]*)', replace_currency, text)
    text = re.sub(r'₹\s*(\d[\d,]*)', replace_currency, text)
    return text


def _fix_numbers(text: str) -> str:
    """Add pauses around important numbers."""
    # Percentage — "74.5%" → "74 point 5 percent"
    text = re.sub(
        r'(\d+)\.(\d+)%',
        lambda m: f"{m.group(1)} point {m.group(2)} percent",
        text
    )
    text = re.sub(r'(\d+)%', r'\1 percent', text)
    return text


def _fix_punctuation(text: str) -> str:
    """Fix punctuation for natural speech pauses."""
    # Multiple spaces to single
    text = re.sub(r'\s+', ' ', text)
    # Ensure sentences end with period
    if text and text[-1] not in '.!?':
        text += '.'
    return text


def _truncate_if_long(text: str) -> str:
    """
    Truncate text if too long for phone call.
    Adds hint to ask for more info.
    """
    if len(text) <= MAX_SAY_LENGTH:
        return text

    # Cut at last sentence boundary before limit
    truncated = text[:MAX_SAY_LENGTH]
    last_period = truncated.rfind('.')
    if last_period > MAX_SAY_LENGTH // 2:
        truncated = truncated[:last_period + 1]

    truncated += " Please ask me if you need more details."
    logger.info(f"[TTS] Response truncated from {len(text)} to {len(truncated)} chars")
    return truncated


def get_voice_config() -> dict:
    """
    Returns voice configuration for Twilio Gather/Say.

    Usage in TwiML:
        gather.say(text, **get_voice_config())
    """
    return {
        "voice":    DEFAULT_VOICE,
        "language": DEFAULT_LANGUAGE,
    }
