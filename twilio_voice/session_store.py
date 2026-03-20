# session_store.py

"""
Minimal but safe session store for Twilio calls.

Handles:
- session creation
- safe updates
- missing keys
- basic cleanup
"""

import time

_sessions = {}

SESSION_TIMEOUT = 300  # 5 minutes


# CORE

def get_session(call_sid):
    """
    Get or create session safely
    """
    if not call_sid:
        return _new_session()

    session = _sessions.get(call_sid)

    if not session:
        session = _new_session()
        _sessions[call_sid] = session

    # update last used time
    session["last_updated"] = time.time()

    return session


def update_session(call_sid, session):
    """
    Safely update session
    """
    if not call_sid:
        return

    if not isinstance(session, dict):
        return

    session["last_updated"] = time.time()
    _sessions[call_sid] = session


def clear_session(call_sid):
    """
    Remove session safely
    """
    if not call_sid:
        return

    _sessions.pop(call_sid, None)


def set_registration(call_sid, reg):
    """
    Store registration number safely
    """
    if not call_sid or not reg:
        return

    session = get_session(call_sid)
    session["registration_number"] = str(reg).upper().strip()


# HELPERS

def _new_session():
    """
    Default session structure
    """
    now = time.time()
    return {
        "registration_number": None,
        "awaiting_otp": False,
        "otp_verified": False,
        "chat_history": [],
        "created_at": now,
        "last_updated": now,
    }



def cleanup_sessions():
    """
    Remove expired sessions
    Prevents memory leak
    """
    now = time.time()
    expired_keys = [
        sid for sid, s in _sessions.items()
        if now - s.get("last_updated", now) > SESSION_TIMEOUT
    ]

    for sid in expired_keys:
        _sessions.pop(sid, None)