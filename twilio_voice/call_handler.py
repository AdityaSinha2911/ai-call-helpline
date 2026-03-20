"""
call_handler.py
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
from fastapi import APIRouter, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather

from twilio_voice.session_store import (
    get_session, update_session, clear_session, set_registration
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

# FastAPI AI backend URL
BACKEND_QUERY_URL = "http://localhost:8000/query"

# Twilio speech settings
SPEECH_TIMEOUT = 3
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
):
    """
    Twilio sends STT result here after student speaks.
    We process through AI and respond.
    """
    confidence = float(Confidence) if Confidence else 0.0

    # Validate speech
    ok, result = process_speech(SpeechResult, confidence)

    response = VoiceResponse()

    if not ok:
        # Low confidence or empty — ask to repeat
        gather = Gather(
            input="speech",
            action="/voice/process",
            method="POST",
            speech_timeout=SPEECH_TIMEOUT,
            language="en-IN",
            enhanced=True,
        )
        gather.say(
            "Sorry, I didn't catch that. Could you please repeat?",
            **VOICE_CONFIG
        )
        response.append(gather)
        return Response(content=str(response), media_type="application/xml")

    query = result
    session = get_session(CallSid)

    logger.info(f"[Call] [{CallSid}] Query: '{query}'")

    # OTP VERIFICATION FLOW 
    # If session is waiting for OTP
    if session.get("awaiting_otp"):
        otp = extract_otp(query)
        if otp:
            reg = session.get("registration_number")
            success, reason = verify_otp_code(reg, otp)
            msg = get_otp_message(reason)

            if success:
                session["awaiting_otp"] = False
                session["otp_verified"]  = True
                update_session(CallSid, session)

            reply = prepare_for_speech(msg)
            _speak_and_listen(response, reply)
            return Response(content=str(response), media_type="application/xml")

    # REGISTRATION NUMBER DETECTION 
    reg = extract_registration_number(query)
    if reg and not session.get("registration_number"):
        set_registration(CallSid, reg)
        session = get_session(CallSid)
        logger.info(f"[Call] [{CallSid}] Reg detected: {reg}")

    # CALL AI BACKEND 
    ai_response = await _call_ai(
        query=query,
        call_sid=CallSid,
        chat_history=session.get("chat_history", []),
        registration_number=session.get("registration_number"),
    )

    # Update chat history
    session["chat_history"].append({"role": "user",      "content": query})
    session["chat_history"].append({"role": "assistant",  "content": ai_response})
    if len(session["chat_history"]) > 6:
        session["chat_history"] = session["chat_history"][-6:]
    update_session(CallSid, session)

    # Speak response
    clean_reply = prepare_for_speech(ai_response)
    _speak_and_listen(response, clean_reply)

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
    """Speak text and start listening again."""
    gather = Gather(
        input="speech",
        action="/voice/process",
        method="POST",
        speech_timeout=SPEECH_TIMEOUT,
        language="en-IN",
        enhanced=True,
    )
    gather.say(text, **VOICE_CONFIG)
    response.append(gather)
    response.redirect("/voice/no-input", method="POST")


async def _call_ai(
    query: str,
    call_sid: str,
    chat_history: list,
    registration_number: str = None,
) -> str:
    return f"You said: {query}"
