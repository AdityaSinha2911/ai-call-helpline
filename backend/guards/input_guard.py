import re  #regex pattern matching, will use for stoping jailbreak
import unicodedata #Used to normalize Unicode characters
import logging #Used for debugging and security monitoring
from dataclasses import dataclass #Used to create structured result objects.

# Creates a logger named after the file
logger = logging.getLogger(__name__)

JAILBREAK_PATTERNS: list[tuple[str, str]] = [   # list of regex rules
    
# These regex patterns detect common prompt injection and jailbreak attempts. If any pattern matches, the input will be blocked before reaching the AI model.

    (r"ignore\s+(all\s+)?previous\s+instructions?",       "instruction_override"),
    (r"forget\s+(all\s+)?previous\s+instructions?",       "instruction_override"),
    (r"disregard\s+(all\s+)?previous\s+instructions?",    "instruction_override"),
    (r"override\s+(your\s+)?(rules?|instructions?)",       "instruction_override"),
    (r"bypass\s+(your\s+)?(rules?|filters?|safety)",      "instruction_override"),
    (r"do\s+not\s+follow\s+(your\s+)?rules?",             "instruction_override"),

    (r"(show|tell|reveal|print|display|repeat|output)\s+(me\s+)?(your\s+)?"
     r"(system\s*prompt|instructions?|rules?|guidelines?|configuration)",  "prompt_extraction"),
    (r"what\s+(are\s+)?(your\s+)?(instructions?|rules?|guidelines?)",      "prompt_extraction"),
    (r"how\s+(were\s+)?you\s+(configured|instructed|programmed|set\s+up)", "prompt_extraction"),

    (r"you\s+are\s+now\s+(a\s+)?(dan|jailbreak|free\s+ai|unrestricted)",  "persona_override"),
    (r"act\s+as\s+(a\s+)?(different|unrestricted|free|uncensored)",        "persona_override"),
    (r"pretend\s+(you\s+are|to\s+be)\s+(a\s+)?(different|general|free)",  "persona_override"),
    (r"switch\s+(to\s+)?(developer|dan|jailbreak|god)\s+mode",            "persona_override"),
    (r"enable\s+(developer|jailbreak|dan|unrestricted)\s+mode",           "persona_override"),
    (r"you\s+have\s+no\s+(restrictions?|rules?|limits?|guidelines?)",     "persona_override"),

    (r"\bdan\b",                    "dan_jailbreak"),
    (r"do\s+anything\s+now",        "dan_jailbreak"),
    (r"jailbreak",                  "dan_jailbreak"),
    (r"grandma\s+trick",            "dan_jailbreak"),
    (r"opposite\s+day",             "dan_jailbreak"),

    (r"what\s+(were\s+)?you\s+trained\s+on",             "model_probing"),
    (r"(show|tell|reveal)\s+(me\s+)?your\s+training",    "model_probing"),
    (r"base\s+model",                                     "model_probing"),
    (r"raw\s+model",                                      "model_probing"),
    (r"without\s+(fine.?tun|lora|adapter)",               "model_probing"),

    (r"in\s+a\s+fictional\s+(world|story|scenario|universe)",  "roleplay_bypass"),
    (r"hypothetically\s+speaking",                             "roleplay_bypass"),
    (r"for\s+a\s+(story|novel|game|movie|script)",             "roleplay_bypass"),
    (r"imagine\s+(you\s+are|if\s+you\s+were)\s+a",            "roleplay_bypass"),
    (r"as\s+a\s+language\s+model\s+without\s+(restrictions?|safety)", "roleplay_bypass"),

    (r"disable\s+(your\s+)?(safety|filters?|guardrails?|restrictions?)", "safety_disable"),
    (r"turn\s+off\s+(your\s+)?(safety|filters?|guardrails?)",            "safety_disable"),
    (r"remove\s+(your\s+)?(restrictions?|limitations?|rules?)",          "safety_disable"),

    (r"<\|system\|>",    "token_injection"),
    (r"<\|user\|>",      "token_injection"),
    (r"<\|assistant\|>", "token_injection"),
    (r"\[INST\]",        "token_injection"),
    (r"\[/INST\]",       "token_injection"),
    (r"###\s*(system|instruction|human|assistant)", "token_injection"),
]

# Compile regex patterns once at startup for better performance.
# This avoids recompiling the same patterns for every request.

_COMPILED_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE), category)
    for p, category in JAILBREAK_PATTERNS
]

# Attackers sometimes replace letters with numbers to bypass filters, like using digit '0' instead of 'o'.

_LEET_MAP: dict[str, str] = {
    '0': 'o', '1': 'i', '3': 'e', '4': 'a',
    '5': 's', '7': 't', '@': 'a', '$': 's', '!': 'i'
}

def _normalize(text: str) -> str:
    """
    Normalize user input before security checks.

    Steps performed:
    1. Unicode normalization (prevents homoglyph attacks)
    2. Convert text to lowercase
    3. Collapse multiple spaces into a single space
    """

    # Convert visually similar Unicode characters into standard form
    normalized = unicodedata.normalize("NFKC", text)

    # Convert to lowercase and remove leading/trailing spaces
    normalized = normalized.lower().strip()

    # Replace multiple spaces with a single space
    normalized = re.sub(r'\s+', ' ', normalized)

    return normalized

def _deleet(text: str) -> str:
    """
    Replace leetspeak characters with their alphabet equivalents.
    Example:
        "1gnore" -> "ignore"
    """
    result = text

    # Replace each leet character with its real letter
    for leet_char, real_char in _LEET_MAP.items():
        result = result.replace(leet_char, real_char)
    return result



# Returned by the input guard to indicate whether the query should be allowed or blocked.

@dataclass
class GuardResult:
    blocked: bool             # True if the query is blocked
    reason: str = ""          # Explanation of why it was blocked
    category: str = ""        # Type of detected attack
    confidence: float = 0.0   # Detection confidence score


# Thresholds declared 
# These limits protect against extremely long prompts that attempt to inject hidden instructions into the model context.
MAX_INPUT_WORDS    = 120   
MAX_INPUT_CHARS    = 800
MIN_INPUT_CHARS    = 2


def check_input(user_input: str) -> GuardResult:
    """
    Main entry point for the Input Guard.

    This function analyzes user input and blocks it if any
    jailbreak or prompt injection pattern is detected.

    Returns:
        GuardResult(blocked=True)  -> input should be rejected
        GuardResult(blocked=False) -> input is safe
    """

    # Reject empty or whitespace-only inputs
    if not user_input or not user_input.strip():
        return GuardResult(blocked=True, reason="Empty input", category="empty")

    if len(user_input) < MIN_INPUT_CHARS:
        return GuardResult(blocked=True, reason="Input too short", category="invalid")

    # Reject extremely long inputs which may contain prompt injections
    if len(user_input) > MAX_INPUT_CHARS:
        logger.warning(f"[InputGuard] Long input blocked: {len(user_input)} chars")
        return GuardResult(
            blocked=True,
            reason=f"Input too long ({len(user_input)} chars). Max allowed: {MAX_INPUT_CHARS}.",
            category="length_attack",
            confidence=0.9
        )

    word_count = len(user_input.split())
    if word_count > MAX_INPUT_WORDS:
        logger.warning(f"[InputGuard] Word limit exceeded: {word_count} words")
        return GuardResult(
            blocked=True,
            reason=f"Input too long ({word_count} words). Possible prompt injection.",
            category="length_attack",
            confidence=0.85
        )

    # Normalize the text (lowercase, unicode normalization, spacing)
    normalized  = _normalize(user_input)

    # Convert leetspeak characters back to normal letters
    de_leetd    = _deleet(normalized)

    # Check input against all known jailbreak patterns
    for compiled_pattern, category in _COMPILED_PATTERNS:
        match = compiled_pattern.search(normalized) or compiled_pattern.search(de_leetd)
        if match:
            matched_text = match.group(0)
            reason = f"Jailbreak attempt detected [{category}]: '{matched_text}'"
            logger.warning(f"[InputGuard] BLOCKED — {reason} | Input: '{user_input[:80]}...'")
            return GuardResult(
                blocked=True,
                reason=reason,
                category=category,
                confidence=1.0
            )

    # Detect repeated words (e.g., "ignore ignore ignore ignore")
    words = normalized.split()
    if len(words) >= 6:
        unique_ratio = len(set(words)) / len(words)

        # If most words are repeated, treat it as a potential attack    
        if unique_ratio < 0.3: 
            logger.warning(f"[InputGuard] Repetition attack blocked. Unique ratio: {unique_ratio:.2f}")
            return GuardResult(
                blocked=True,
                reason="Highly repetitive input detected — possible model confusion attack.",
                category="repetition_attack",
                confidence=0.8
            )
        
    # If no attack patterns were detected, the input is considered safe
    return GuardResult(blocked=False)
