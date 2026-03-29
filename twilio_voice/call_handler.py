"""
Main Twilio webhook handler for incoming voice calls.

Flow:
  Student calls +13185965065
       ↓
  Twilio → POST /voice/incoming
       ↓
  Greet student, start listening
       ↓
  Student speaks → Twilio STT
       ↓
  POST /voice/process (with SpeechResult)
       ↓
  stt_handler cleans text
       ↓
  FastAPI AI backend processes query
       ↓
  tts_handler cleans response
       ↓
  Speak response back, listen again
       ↓
  Loop until student hangs up
"""

import logging
import httpx
import asyncio
import random
from fastapi import APIRouter, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather


from twilio_voice.session_store import (
    get_session, update_session, clear_session, 
    set_registration, set_pending_query, pop_pending_query  
)
from twilio_voice.stt_handler import (
    process_speech, extract_registration_number, extract_otp
)
from twilio_voice.tts_handler import prepare_for_speech, get_voice_config
from twilio_voice.otp_helper import send_otp, verify_otp_code, get_otp_message
from fastapi import APIRouter, Request
from fastapi.responses import Response

from backend.guards.topic_guard import detect_intent
from backend.database import create_ticket


logger = logging.getLogger("helpline.call_handler")

router = APIRouter(prefix="/voice", tags=["Voice"])

# store background responses
ASYNC_RESPONSES = {} 

# FastAPI AI backend URL
BACKEND_QUERY_URL = "http://localhost:8000/query"

# Twilio speech settings
SPEECH_TIMEOUT = 8
DTMF_TIMEOUT = 10  #waiting time for keypad input
VOICE_CONFIG   = get_voice_config()

# poll timing increased
ASYNC_POLL_PAUSE_SECONDS = 3
MAX_ASYNC_POLL_ATTEMPTS = 20

GREETING_LINES = [
    "Hello! Welcome to the college helpline. How may I assist you today?",
    "Good day! You have reached the college helpline. How can I help you?",
    "Hello and welcome to the college helpline. Please let me know how I can assist you.",
    "Welcome to the college helpline. I am here to help you. Please go ahead.",
    "Hello! Thank you for calling the college helpline. How may I assist you today?"
]

FOLLOWUP_LINES = [
    "Is there anything else I can assist you with?",
    "Do you have any other queries?",
    "Please let me know if you need further assistance.",
    "Would you like help with anything else?",
    "Feel free to ask if you have any other questions."
]


# INCOMING CALL 
@router.post("/incoming")
async def incoming_call(
    request: Request,
    CallSid: str = Form(...)
):
    """
    Twilio hits this endpoint when student calls your number.
    We greet and start listening.
    """
    logger.info(f"[Call] Incoming — CallSid: {CallSid}")

    # Fresh session for this call
    clear_session(CallSid)

    response = VoiceResponse()

    gather = Gather(
        input="speech",
        action="/voice/process",
        method="POST",
        speech_timeout=SPEECH_TIMEOUT,
        language="en-IN",
        enhanced=True,
    )
    gather.say(
        random.choice(GREETING_LINES),
        **VOICE_CONFIG
    )
    response.append(gather)
    response.redirect("/voice/no-input", method="POST")

    return Response(content=str(response), media_type="application/xml")


# PROCESS SPEECH 
@router.post("/process")
async def process_speech_input(
    request: Request,
    CallSid: str    = Form(...),
    SpeechResult: str = Form(default=""),
    Confidence: str   = Form(default="0"),
    Digits: str       = Form(default=""),
):
    """
    Twilio sends STT result here after student speaks.
    We process through AI and respond.
    """
    confidence = float(Confidence) if Confidence else 0.0
    response = VoiceResponse()
    session = get_session(CallSid)

    # PRIORITY — if Digits received, use that directly
    # keypad is more reliable than speech
    if Digits:
        query = Digits.replace("#", "").strip()
        logger.info(f"[Call] [{CallSid}] DTMF input: '{query}'")
    else:
        # Fall back to speech
        ok, result = process_speech(SpeechResult, confidence)
        if not ok:
            gather = Gather(
                input="dtmf speech",
                action="/voice/process",
                method="POST",
                speech_timeout=SPEECH_TIMEOUT,
                language="en-IN",
            )
            gather.say(
                "Sorry, I didn't catch that. Please repeat or use your keypad.",
                **VOICE_CONFIG
            )
            response.append(gather)
            return Response(content=str(response), media_type="application/xml")
        query = result

    # Student spoke — reset silence strike counter
    session["no_input_strikes"] = 0
    update_session(CallSid, session)

    logger.info(f"[Call] [{CallSid}] Query: '{query}'")

    # OTP VERIFICATION FLOW 
    # OTP FLOW — use keypad
    if session.get("awaiting_otp"):
        otp = query  # digits entered directly, no extraction needed
        if otp.isdigit() and len(otp) == 6:
            reg = session.get("registration_number")
            success, reason = verify_otp_code(reg, otp)
            msg = get_otp_message(reason)

            if success:
                session["awaiting_otp"] = False
                session["otp_verified"] = True
                update_session(CallSid, session)

            reply = prepare_for_speech(msg)
            _speak_and_listen(response, reply)
            return Response(content=str(response), media_type="application/xml")
        else:
            # Invalid OTP format
            _ask_for_digits(
                response,
                "Please enter your 6-digit OTP using keypad and press hash at end.",
                num_digits=6
            )
            return Response(content=str(response), media_type="application/xml")
    
    if session.get("pending_ticket_issue"):
        confirmed = query.strip().lower()
        if confirmed in ("yes", "yeah", "haan", "ok", "okay", "sure", "please", "yes please"):
            issue = session.pop("pending_ticket_issue")
            update_session(CallSid, session)
            student_id = session.get("registration_number")
            ticket_id = create_ticket(student_id=student_id, issue=issue, call_id=CallSid,category=None)
            if ticket_id:
                reply = (
                    f"Done. Your ticket number is {ticket_id}. "
                    f"Our team will contact you within 24 hours. "
                    f"Is there anything else I can help you with?"
                )
            else:
                reply = "I'm sorry, I could not register your complaint right now. Please try again."
            _speak_and_listen(response, prepare_for_speech(reply))
            return Response(content=str(response), media_type="application/xml")

        elif confirmed in ("no", "nahi", "nope", "nah"):
            session.pop("pending_ticket_issue", None)
            update_session(CallSid, session)
            reply = "Okay, no ticket raised. Is there anything else I can help you with?"
            _speak_and_listen(response, prepare_for_speech(reply))
            return Response(content=str(response), media_type="application/xml")
        
        # If response is unclear, fall through to normal AI processing
        session.pop("pending_ticket_issue", None)
        update_session(CallSid, session)

    # REG NUMBER DETECTION
    if query.isdigit() and len(query) == 8:
        reg = query
    else:
        reg = extract_registration_number(query)

    if reg and not session.get("registration_number"):
        from backend.database import get_student
        student_data = get_student(reg)
        set_registration(CallSid, reg, student_data=student_data)
        session = get_session(CallSid)
        logger.info(f"[Call] [{CallSid}] Reg detected and student cached: {reg}")

        # Resume original question if student gave reg number
        pending = pop_pending_query(CallSid)
        if pending:
            query = pending

    # Ask for reg number if needed
    personal_keywords = ['fee', 'fees', 'attendance', 
                         'result', 'marks', 'hostel']
    needs_personal = any(w in query.lower() for w in personal_keywords)

    if needs_personal and not session.get("registration_number"):
        set_pending_query(CallSid, query) #uses session handler
        _ask_for_digits(
            response,
            "Sure! Please enter your 8-digit registration number "
            "using the keypad and press hash when done.",
            num_digits=8
        )
        return Response(content=str(response), media_type="application/xml")

    # CALL AI BACKEND 
    # check if previous response is ready
    if CallSid in ASYNC_RESPONSES:
        ai_response = ASYNC_RESPONSES.pop(CallSid)

        clean_reply = prepare_for_speech(ai_response)
        _speak_and_listen(response, clean_reply)

        return Response(content=str(response), media_type="application/xml")
    
    # otherwise -- start background task
    session["async_poll_attempts"] = 0
    update_session(CallSid, session)

    asyncio.create_task(
        _process_ai_background(CallSid, query)
    )

    # immediate response (IMPORTANT)
    _start_async_polling(
        response,
        "Please wait while I check your information."
    )

    return Response(content=str(response), media_type="application/xml")


@router.post("/poll")
async def poll_async_response(CallSid: str = Form(...)):
    """Twilio polling loop for background AI responses."""
    response = VoiceResponse()
    session = get_session(CallSid)

    if CallSid in ASYNC_RESPONSES:
        ai_response = ASYNC_RESPONSES.pop(CallSid)
        session["async_poll_attempts"] = 0
        update_session(CallSid, session)

        clean_reply = prepare_for_speech(ai_response)
        _speak_and_listen(response, clean_reply)
        return Response(content=str(response), media_type="application/xml")

    attempts = int(session.get("async_poll_attempts", 0)) + 1
    session["async_poll_attempts"] = attempts
    update_session(CallSid, session)

    if attempts >= MAX_ASYNC_POLL_ATTEMPTS:
        _speak_and_listen(
            response,
            "I need a little more time to check this. Please ask again in a moment."
        )
        session["async_poll_attempts"] = 0
        update_session(CallSid, session)
        return Response(content=str(response), media_type="application/xml")

    response.pause(length=ASYNC_POLL_PAUSE_SECONDS)
    response.redirect("/voice/poll", method="POST")
    return Response(content=str(response), media_type="application/xml")

# NO INPUT
# Strikes before hangup. 2 strikes = one re-prompt then goodbye (~15 sec total silence).
_MAX_NO_INPUT_STRIKES = 2

@router.post("/no-input")
async def no_input(
    request: Request,
    CallSid: str = Form(default=""),
):
    """
    Called when student doesn't speak.

    Strike 1  → re-prompt, keep listening
    Strike 2+ → say goodbye and hang up

    Edge-case guard: if a background AI task is still running, we must NOT
    hang up here. Instead redirect back to /poll to keep the call alive.
    """
    logger.info(f"[Call] [{CallSid}] No input")

    session = get_session(CallSid)

    # Guard — AI still processing: keep the call alive, do not hang up
    if CallSid in ASYNC_RESPONSES or int(session.get("async_poll_attempts", 0)) > 0:
        response = VoiceResponse()
        response.pause(length=ASYNC_POLL_PAUSE_SECONDS)
        response.redirect("/voice/poll", method="POST")
        return Response(content=str(response), media_type="application/xml")

    strikes = int(session.get("no_input_strikes", 0)) + 1
    session["no_input_strikes"] = strikes
    update_session(CallSid, session)

    response = VoiceResponse()

    if strikes >= _MAX_NO_INPUT_STRIKES:
        # Enough silence — say goodbye cleanly
        response.say("We haven't heard from you. Thank you for calling. Goodbye!", **VOICE_CONFIG)
        response.hangup()
        return Response(content=str(response), media_type="application/xml")

    # Strike 1 — one re-prompt, then loop back here if still silent
    gather = Gather(
        input="speech",
        action="/voice/process",
        method="POST",
        speech_timeout=SPEECH_TIMEOUT,
        language="en-IN",
        enhanced=True,
    )
    gather.say("Are you still there? Please speak your query.", **VOICE_CONFIG)
    response.append(gather)
    response.redirect("/voice/no-input", method="POST")

    return Response(content=str(response), media_type="application/xml")

# CALL STATUS 
@router.post("/status")
async def call_status(
    CallSid: str    = Form(...),
    CallStatus: str = Form(...),
):
    """Twilio calls this when call ends."""
    logger.info(f"[Call] [{CallSid}] Status: {CallStatus}")

    if CallStatus in ("completed", "failed", "busy", "no-answer"):
        clear_session(CallSid)

    return Response(content="", media_type="text/plain")


# HELPERS

# If AI response already ends with a question, don't add a redundant prompt.
_QUESTION_SIGNALS = (
    "?",
    "please let me know",
    "can you tell me",
    "could you tell me",
    "do you want",
    "would you like",
    "please confirm",
    "please enter",
    "please say",
    "is that correct",
    "anything else",
    "how can i help",
    "press ",          # e.g. "press 1 for yes"
)

def _response_is_question(text: str) -> bool:
    lowered = text.lower().strip()
    return any(lowered.endswith(sig) or sig in lowered for sig in _QUESTION_SIGNALS)

def _speak_and_listen(response: VoiceResponse, text: str) -> None:
    # speak the response first
    response.say(text, **VOICE_CONFIG)

    # Start listening AFTER speech finishes
    gather = Gather(
        input="speech",
        action="/voice/process",
        method="POST",
        speech_timeout="auto",
        language="en-IN",
        enhanced=True,
    )

    # Only add a prompt when the AI response is NOT already a question.
    # If AI already asked something (e.g. "Anything else?"), stay silent —
    # adding "Please tell me your next query" on top overrides it and sounds broken.
    if not _response_is_question(text):
        gather.say(random.choice(FOLLOWUP_LINES), **VOICE_CONFIG)

    response.append(gather)

    # fallback loop (instead of hangup)
    response.redirect("/voice/no-input", method="POST")

# Uses BOTH speech and keypad
def _ask_for_digits(
    response: VoiceResponse,
    text: str,
    num_digits: int,
    action: str = "/voice/process"
) -> None:
    gather = Gather(
        input="dtmf speech",     # accept both
        action=action,
        method="POST",
        finish_on_key="#",       # press # to submit
        timeout=DTMF_TIMEOUT,
        num_digits=num_digits,   # auto-submit after N digits
        speech_timeout="auto",
        language="en-IN",
    )
    gather.say(text, **VOICE_CONFIG)
    response.append(gather)
    response.redirect("/voice/no-input", method="POST")


def _start_async_polling(response: VoiceResponse, text: str) -> None:
    """Speak a short waiting message, then poll for background completion."""
    response.say(text, **VOICE_CONFIG)
    response.pause(length=ASYNC_POLL_PAUSE_SECONDS)
    response.redirect("/voice/poll", method="POST")


async def _call_ai(
    query: str,
    call_sid: str,
    chat_history: list,
    registration_number: str = None,
) -> str: #real-time type response is implied
    try:
        payload = {
            "query": query,
            "call_sid": call_sid,
            "chat_history": chat_history,
            "registration_number": registration_number,
        }

        async with httpx.AsyncClient(timeout=90.0) as client: #timeout time increased
            resp = await client.post(BACKEND_QUERY_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("answer", "Sorry, I could not get a response.")

    except Exception as e:
        logger.error(f"[AI] Error calling backend: {e}")
        return "Sorry, I am having trouble right now. Please try again."
    
# background ai worker
async def _process_ai_background(call_sid: str, query: str):
    session = get_session(call_sid) 
    # STEP 1: Detect if this is a PROBLEM or a QUERY
    intent_result = detect_intent(query)
    student_id = session.get("registration_number")

    # STEP 2: Route based on intent
    if intent_result["needs_ticket"]:

        if student_id:
            # Ask for confirmation BEFORE raising ticket
            ai_response = (
                "I understand you're facing an issue. "
                "Should I raise a support ticket so our team can follow up with you? "
                "Please say yes or no."
            )
            # Store pending ticket intent so next response can create it
            session = get_session(call_sid)
            session["pending_ticket_issue"] = query
            update_session(call_sid, session)

        else:
            ai_response = (
                "I'd like to help you with that. "
                "Please enter your 8-digit registration number "
                "on the keypad so I can raise a ticket for you."
            )

    else:
        # STEP 3: It's a QUERY → call AI normally
        ai_response = await _call_ai(
            query=query,
            call_sid=call_sid,
            chat_history=session.get("chat_history", []),
            registration_number=student_id,
        )

    # STEP 4: Update chat history
    session = get_session(call_sid)
    history = session.get("chat_history", [])
    history.append({"role": "user",      "content": query})
    history.append({"role": "assistant", "content": ai_response})
    session["chat_history"] = history[-10:]
    update_session(call_sid, session)

    # STEP 5: Store response for poll pickup
    ASYNC_RESPONSES[call_sid] = ai_response