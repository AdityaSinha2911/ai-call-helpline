"""
Runs AFTER input_guard passes.
Only allows college administrative queries through.

Strategy:
  1. Hard-block list — explicitly forbidden topics (checked first, fast)
  2. Allow-list with keyword scoring — topic must score above threshold
  3. Scoring approach means partial matches still work
     e.g. "what are my exam results" scores high on "exams" topic
"""

import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# HARD BLOCK LIST
# These topics are explicitly forbidden regardless of context.
# Checked first — if any match, query is rejected immediately.
BLOCKED_TOPICS: dict[str, list[str]] = {
    "sports": [
        "cricket", "football", "ipl", "fifa", "nba", "icc", "match score",
        "world cup", "olympic", "tennis", "badminton", "kabaddi", "hockey",
        "score", "wicket", "century", "goal", "tournament bracket"
    ],
    "politics": [
        "election", "minister", "parliament", "modi", "bjp", "congress",
        "political party", "vote", "mla", "mp ", "president of india",
        "government policy", "lok sabha", "rajya sabha"
    ],
    "entertainment": [
        "movie", "film", "actor", "actress", "bollywood", "hollywood",
        "web series", "netflix", "amazon prime", "hotstar", "ott",
        "song lyrics", "album", "celebrity gossip"
    ],
    "hacking": [
        "hack", "crack", "exploit", "vulnerability", "sql injection",
        "xss", "phishing", "malware", "virus", "ransomware", "ddos",
        "brute force", "penetration test", "zero day"
    ],
    "harmful": [
        "weapon", "bomb", "drug", "narcotic", "suicide", "self harm",
        "kill", "murder", "illegal", "darkweb", "dark web"
    ],
    "general_knowledge": [
        "capital of", "who invented", "history of", "geography",
        "science fact", "math problem", "equation",
        "translate", "recipe", "cook", "weather", "news today",
        "stock price", "crypto", "bitcoin", "forex"
    ],
    "personal": [
        "girlfriend", "boyfriend", "dating", "love advice",
        "relationship", "marriage", "breakup", "propose"
    ]
}

# Flatten for fast lookup
_ALL_BLOCKED: list[tuple[str, str]] = [
    (keyword, category)
    for category, keywords in BLOCKED_TOPICS.items()
    for keyword in keywords
]

# ALLOWED TOPICS WITH WEIGHTED KEYWORDS
# Format: { topic_name: { keyword: weight } }
# Weight reflects how strongly a keyword signals this topic.
# A query needs to score >= SCORE_THRESHOLD to be allowed.
ALLOWED_TOPICS: dict[str, dict[str, float]] = {
    "fees": {
        "fee": 1.0, "fees": 1.0, "tuition": 1.0, "payment": 0.8,
        "challan": 1.0, "dues": 0.9, "fine": 0.6, "penalty": 0.7,
        "late fee": 1.0, "semester fee": 1.0, "hostel fee": 1.0,
        "pay": 0.5, "paid": 0.6, "unpaid": 0.8, "pending fee": 1.0,
        "fee receipt": 1.0, "fee structure": 1.0, "refund": 0.7,
    },
    "attendance": {
        "attendance": 1.0, "absent": 0.9, "present": 0.7,
        "bunk": 0.9, "leave": 0.6, "short attendance": 1.0,
        "condonation": 1.0, "attendance percentage": 1.0,
        "medical leave": 0.8, "detention": 0.8, "75%": 0.9,
        "attendance shortage": 1.0,
    },
    "exams": {
        "exam": 1.0, "examination": 1.0, "test": 0.7, "quiz": 0.7,
        "marks": 0.8, "result": 0.9, "grade": 0.8, "gpa": 1.0,
        "sgpa": 1.0, "cgpa": 1.0, "backlog": 1.0, "reappear": 1.0,
        "datesheet": 1.0, "date sheet": 1.0, "timetable": 0.8,
        "hall ticket": 1.0, "admit card": 1.0, "re-evaluation": 1.0,
        "re evaluation": 1.0, "internal marks": 1.0, "external marks": 1.0,
        "practical exam": 1.0, "viva": 0.8, "semester result": 1.0,
    },
    "admissions": {
        "admission": 1.0, "apply": 0.5, "application": 0.6,
        "enrollment": 1.0, "enroll": 1.0, "register": 0.7,
        "document": 0.5, "certificate": 0.6, "transfer": 0.7,
        "migration": 0.8, "eligibility": 0.7, "cutoff": 0.8,
        "admission process": 1.0, "admission form": 1.0,
    },
    "hostel": {
        "hostel": 1.0, "room": 0.4, "mess": 0.8, "warden": 1.0,
        "accommodation": 0.8, "dormitory": 1.0, "hostel room": 1.0,
        "hostel fee": 1.0, "hostel complaint": 1.0, "roommate": 0.8,
        "hostel allotment": 1.0, "hostel rules": 1.0,
    },
    "library": {
        "library": 1.0, "book": 0.5, "issue book": 1.0,
        "return book": 1.0, "librarian": 1.0, "reading room": 1.0,
        "library fine": 1.0, "library card": 1.0, "borrow": 0.6,
    },
    "scholarships": {
        "scholarship": 1.0, "stipend": 1.0, "financial aid": 1.0,
        "grant": 0.6, "fee waiver": 1.0, "merit scholarship": 1.0,
        "scholarship application": 1.0, "scholarship amount": 1.0,
        "scholarship eligibility": 1.0,
    },
    "documents": {
        "bonafide": 1.0, "character certificate": 1.0, "tc": 0.7,
        "transfer certificate": 1.0, "marksheet": 1.0, "transcript": 1.0,
        "migration certificate": 1.0, "provisional certificate": 1.0,
        "degree certificate": 1.0, "identity card": 0.8, "id card": 0.8,
        "duplicate id": 1.0,
    },
    "general_college": {
    "college": 0.6,"university": 0.6,"department": 0.6,"faculty": 0.6,
    "professor": 0.6,"class": 0.5,"lecture": 0.6,
    "campus": 0.6,"student": 0.5,"holiday": 0.7,
    "schedule": 0.6,"office timing": 0.9,"contact number": 0.8,
    "helpline": 0.9,"registration number": 1.0,"student id": 0.9,
    },
    "support_ticket": {
        "complaint": 0.9, "problem": 0.7, "issue": 0.7,
        "not working": 0.8, "broken": 0.5, "report": 0.5,
        "raise ticket": 1.0, "support": 0.7, "help": 0.7,
        "grievance": 1.0,
    }
}

# Minimum score for a query to be considered on-topic
SCORE_THRESHOLD = 0.5

# RESULT DATACLASS
@dataclass
class TopicResult:
    allowed: bool
    topic: str = ""
    score: float = 0.0
    blocked_reason: str = ""

# MAIN CLASSIFICATION FUNCTION
def classify_topic(user_input: str) -> TopicResult:

    normalized = user_input.lower().strip()
    normalized = re.sub(r'\s+', ' ', normalized)

    # Hard block list check
    for keyword, category in _ALL_BLOCKED:
        # Use word boundary for short keywords to avoid false positives
        # e.g. "score" shouldn't block "scorecard" in college context
        if len(keyword) <= 4:
            if re.search(rf'\b{re.escape(keyword)}\b', normalized):
                reason = f"Off-topic query — category '{category}' is outside my scope."
                logger.info(f"[TopicGuard] BLOCKED [{category}] keyword='{keyword}' | '{normalized[:60]}'")
                return TopicResult(allowed=False, blocked_reason=reason)
        else:
            if keyword in normalized:
                reason = f"Off-topic query — category '{category}' is outside my scope."
                logger.info(f"[TopicGuard] BLOCKED [{category}] keyword='{keyword}' | '{normalized[:60]}'")
                return TopicResult(allowed=False, blocked_reason=reason)

    # Score against allowed topics
    topic_scores: dict[str, float] = {}

    for topic, keyword_weights in ALLOWED_TOPICS.items():
        score = 0.0
        for keyword, weight in keyword_weights.items():
            if keyword in normalized:
                score += weight
        if score > 0:
            topic_scores[topic] = score

    if not topic_scores:
        logger.info(f"[TopicGuard] NO MATCH | '{normalized[:60]}'")
        return TopicResult(
            allowed=False,
            blocked_reason="I can only help with college-related queries such as fees, attendance, exams, hostel, or documents."
        )

    # Pick the highest-scoring topic
    best_topic = max(topic_scores, key=lambda t: topic_scores[t])
    best_score = topic_scores[best_topic]

    if best_score < SCORE_THRESHOLD:
        logger.info(f"[TopicGuard] LOW SCORE {best_score:.2f} for topic '{best_topic}' | '{normalized[:60]}'")
        return TopicResult(
            allowed=False,
            blocked_reason="Your query doesn't seem to be about college administration. I can help with fees, attendance, exams, hostel, or documents."
        )

    logger.info(f"[TopicGuard] ALLOWED topic='{best_topic}' score={best_score:.2f} | '{normalized[:60]}'")
    return TopicResult(allowed=True, topic=best_topic, score=best_score)
