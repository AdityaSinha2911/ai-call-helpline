"""
session_store.py

In-memory session store for Twilio voice calls.
Each call gets its own session identified by CallSid.

Stores:
- registration_number
- otp state
- chat history
- pending query (for DTMF flow)
- timestamps for cleanup
"""

import time
import threading
import logging

logger = logging.getLogger("helpline.session_store")

# All active call sessions live here
_sessions: dict = {}

# Lock for thread safety
# FastAPI runs async but can have concurrent requests
_lock = threading.Lock()

SESSION_TIMEOUT = 600  # 10 minutes — enough for any call


# CORE FUNCTIONS

def get_session(call_sid: str) -> dict:
    """
    Get existing session or create a new one.
    Always returns a valid session dict.
    """
    if not call_sid:
        return _new_session()

    with _lock:
        if call_sid not in _sessions:
            _sessions[call_sid] = _new_session()
            logger.debug(f"[Session] Created new session: {call_sid}")

        session = _sessions[call_sid]
        session["last_updated"] = time.time()
        return session


def update_session(call_sid: str, session: dict) -> None:
    """
    Save updated session back to store.
    """
    if not call_sid or not isinstance(session, dict):
        return

    with _lock:
        session["last_updated"] = time.time()
        _sessions[call_sid] = session
        logger.debug(f"[Session] Updated: {call_sid}")


def clear_session(call_sid: str) -> None:
    """
    Delete session when call ends.
    """
    if not call_sid:
        return

    with _lock:
        removed = _sessions.pop(call_sid, None)
        if removed:
            logger.debug(f"[Session] Cleared: {call_sid}")


def set_registration(call_sid: str, reg: str) -> None:
    """
    Store registration number in session.
    Bug fix: saves back to store after updating.
    """
    if not call_sid or not reg:
        return

    session = get_session(call_sid)
    session["registration_number"] = str(reg).upper().strip()
    update_session(call_sid, session)  # ← critical fix
    logger.info(f"[Session] Reg saved: {call_sid} → {reg}")


def set_pending_query(call_sid: str, query: str) -> None:
    """
    Save the original query when waiting for reg number.
    Used in DTMF flow.
    """
    if not call_sid or not query:
        return

    session = get_session(call_sid)
    session["pending_query"] = query.strip()
    update_session(call_sid, session)


def pop_pending_query(call_sid: str) -> str | None:
    """
    Get and remove pending query from session.
    Returns None if no pending query exists.
    """
    session = get_session(call_sid)
    query = session.pop("pending_query", None)
    if query:
        update_session(call_sid, session)
        logger.debug(f"[Session] Pending query restored: {call_sid}")
    return query


def get_session_count() -> int:
    """
    Returns number of active sessions.
    Useful for monitoring.
    """
    with _lock:
        return len(_sessions)


# INTERNAL
def _new_session() -> dict:
    """
    Default structure for every new call session.
    """
    now = time.time()
    return {
        "registration_number": None,
        "awaiting_otp":        False,
        "otp_verified":        False,
        "chat_history":        [],
        "pending_query":       None,
        "created_at":          now,
        "last_updated":        now,
    }


def cleanup_sessions() -> int:
    """
    Remove sessions inactive for SESSION_TIMEOUT seconds.
    Call this periodically to prevent memory leaks.
    Returns number of sessions removed.
    """
    now = time.time()
    removed = 0

    with _lock:
        expired = [
            sid for sid, s in _sessions.items()
            if now - s.get("last_updated", now) > SESSION_TIMEOUT
        ]
        for sid in expired:
            _sessions.pop(sid, None)
            removed += 1

    if removed:
        logger.info(f"[Session] Cleaned up {removed} expired sessions.")

    return removed