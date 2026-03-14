"""
Runs AFTER the model generates a response.
Catches cases where the model slipped through input/topic guards.

Checks:
  1. Model leaked system prompt or internal config
  2. Model answered an off-topic question anyway
  3. Response is dangerously long (model went off-script)
  4. Response contains PII that should not be exposed
  5. Response contains harmful content
"""

import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# UNSAFE RESPONSE PATTERNS
# Things the model should never say back to the user.
UNSAFE_OUTPUT_PATTERNS: list[tuple[str, str]] = [
    # Model leaking its own config / system prompt
    (r"(my\s+)?(system\s+prompt|instructions?\s+(are|say|tell)|i\s+was\s+told\s+to)",
     "system_leak"),
    (r"(i\s+am\s+programmed\s+to|i\s+was\s+(programmed|configured|instructed)\s+to"
     r"|my\s+rules?\s+are)",
     "system_leak"),
    (r"(according\s+to\s+my\s+(instructions?|programming|configuration))",
     "system_leak"),

    # Model acting as a general/unrestricted AI
    (r"(as\s+a\s+(general|unrestricted|free|uncensored)\s+(ai|assistant|model))",
     "persona_slip"),
    (r"(without\s+(any\s+)?(restrictions?|limitations?|rules?))",
     "persona_slip"),
    (r"(i\s+can\s+(now\s+)?(answer|help\s+with)\s+anything)",
     "persona_slip"),

    # Model echoing back jailbreak phrases (indicates it processed them)
    (r"(ignore\s+(all\s+)?previous\s+instructions?)",
     "jailbreak_echo"),
    (r"(you\s+are\s+now\s+(a\s+)?dan)",
     "jailbreak_echo"),

    # Potential harmful content
    (r"(how\s+to\s+(make|build|create|synthesize)\s+(bomb|weapon|explosive|drug))",
     "harmful_content"),
    (r"(step\s+by\s+step\s+(to\s+)?(hack|crack|exploit|break\s+into))",
     "harmful_content"),
]

_COMPILED_OUTPUT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE), category)
    for p, category in UNSAFE_OUTPUT_PATTERNS
]

# PII DETECTION PATTERNS -(Personally Identifiable Information)
# Catches if model accidentally included raw sensitive data in wrong format
PII_PATTERNS: list[tuple[str, str]] = [
    # Raw phone numbers in response (model shouldn't output these)
    (r'\b[6-9]\d{9}\b',           "phone_number"),
    # Aadhaar-like patterns
    (r'\b\d{4}\s?\d{4}\s?\d{4}\b', "aadhaar_like"),
    # OTP in response (model should never output OTPs)
    (r'\b(otp\s*(is|:)\s*\d{4,6}|\d{6}\s*is\s*(your|the)\s*otp)\b', "otp_leak"),
]

_COMPILED_PII: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE), label)
    for p, label in PII_PATTERNS
]

# RESPONSE LENGTH CONTROLS
MAX_RESPONSE_WORDS = 80      # Hard limit — model configured for 50, buffer to 80
TRUNCATION_WORDS   = 60      # Soft truncation target when over limit


# RESULT DATACLASS
@dataclass
class OutputResult:
    safe: bool
    response: str        # Final response to send to user (possibly truncated)
    reason: str = ""     # Why it was blocked (if safe=False)
    category: str = ""   # Category of issue found


# MAIN VALIDATION FUNCTION
def validate_output(model_response: str) -> OutputResult:
    allowed_words = ["helpline", "contact", "office", "department", "support"]
    # Empty response check 
    if not model_response or not model_response.strip():
        logger.warning("[OutputGuard] Empty model response")
        return OutputResult(
            safe=False,
            response="",
            reason="Model returned empty response.",
            category="empty_response"
        )

    response = model_response.strip()

    # Unsafe pattern check
    response_lower = response.lower()
    for pattern, category in _COMPILED_OUTPUT_PATTERNS:
        if pattern.search(response_lower):
            logger.warning(f"[OutputGuard] BLOCKED [{category}] | Response: '{response[:80]}'")
            return OutputResult(
                safe=False,
                response="",
                reason=f"Response blocked — unsafe content detected [{category}].",
                category=category
            )

    # PII check 
    for pattern, pii_type in _COMPILED_PII:
    
        # Allow official contact numbers 
        if pii_type == "phone_number" and any(word in response.lower() for word in allowed_words):
            continue

        if pattern.search(response):
            logger.warning(f"[OutputGuard] PII detected [{pii_type}] in response")

            # For PII, redact instead of blocking the response
            response = pattern.sub("[REDACTED]", response)

            logger.info(f"[OutputGuard] PII redacted [{pii_type}]")

    # Length control 
    words = response.split()
    if len(words) > MAX_RESPONSE_WORDS:
        logger.warning(f"[OutputGuard] Response too long: {len(words)} words. Truncating.")
        response = ' '.join(words[:TRUNCATION_WORDS]) + "..."

    #All checks passed 
    logger.debug(f"[OutputGuard] SAFE | {len(response.split())} words")
    return OutputResult(safe=True, response=response)
