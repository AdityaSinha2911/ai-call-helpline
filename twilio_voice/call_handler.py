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



logger = logging.getLogger("helpline.call_handler")

router = APIRouter(prefix="/voice", tags=["Voice"])

# store background responses
ASYNC_RESPONSES = {} 

# FastAPI AI backend URL
BACKEND_QUERY_URL = "http://localhost:8000/query"

# Twilio speech settings
SPEECH_TIMEOUT = 3
DTMF_TIMEOUT = 10  #waiting time for keypad input
VOICE_CONFIG   = get_voice_config()


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
        "Hello! Welcome to the college helpline. How can I assist you today?",
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

    # REG NUMBER DETECTION
    if query.isdigit() and len(query) == 8:
        reg = query
    else:
        reg = extract_registration_number(query)

    if reg and not session.get("registration_number"):
        set_registration(CallSid, reg)
        session = get_session(CallSid)
        logger.info(f"[Call] [{CallSid}] Reg detected: {reg}")

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
    asyncio.create_task(
        _process_ai_background(CallSid, query, session)
    )

    # immediate response (IMPORTANT)
    _speak_and_listen(
        response,
        "Please wait while I check your information."
    )

    return Response(content=str(response), media_type="application/xml")

# NO INPUT 
@router.post("/no-input")
async def no_input(CallSid: str = Form(...)):
    """Called when student doesn't speak."""
    logger.info(f"[Call] [{CallSid}] No input")

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
        "Are you still there? Please speak your query.",
        **VOICE_CONFIG
    )
    response.append(gather)
    response.say("Thank you for calling. Goodbye!", **VOICE_CONFIG)
    response.hangup()

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
def _speak_and_listen(response: VoiceResponse, text: str) -> None:
    #speak the response first
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

    gather.say(
        "Please tell me your next query.",
        **VOICE_CONFIG
    )

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
        speech_timeout=SPEECH_TIMEOUT,
        language="en-IN",
    )
    gather.say(text, **VOICE_CONFIG)
    response.append(gather)
    response.redirect("/voice/no-input", method="POST")


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

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(BACKEND_QUERY_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("answer", "Sorry, I could not get a response.")

    except Exception as e:
        logger.error(f"[AI] Error calling backend: {e}")
        return "Sorry, I am having trouble right now. Please try again."
    
# background ai worker
async def _process_ai_background(call_sid, query, session):
    ai_response = await _call_ai(
        query=query,
        call_sid=call_sid,
        chat_history=session.get("chat_history", []),
        registration_number=session.get("registration_number"),
    )

    # store response for next turn
    ASYNC_RESPONSES[call_sid] = ai_response
