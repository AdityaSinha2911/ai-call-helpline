"""
Main Twilio webhook handler for incoming voice calls.

Flow:
  Student calls the helpline number
       ↓
  Twilio → POST /voice/incoming
       ↓
  Greet student, start listening
       ↓
  Student speaks → Twilio STT
       ↓
  POST /voice/process (with SpeechResult)
       ↓
  stt_handler cleans + corrects text
       ↓
  Exit phrase check (immediate — no background task needed)
       ↓
  OTP / ticket confirmation / reg number flow (if active)
       ↓
  AI backend processes query (background task)
       ↓
  Poll loop waits for AI response
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

from backend.guards.topic_guard import detect_intent
from backend.database import create_ticket, get_student

logger = logging.getLogger("helpline.call_handler")

router = APIRouter(prefix="/voice", tags=["Voice"])

# store background responses
# background AI tasks write their result here using CallSid as the key
# the /poll endpoint keeps checking this dict until the result appears
# "__EXIT__" is a special value — means student wants to hang up
ASYNC_RESPONSES: dict[str, str] = {}

# FastAPI AI backend URL
BACKEND_QUERY_URL = "http://localhost:8000/query"

# Twilio speech settings
SPEECH_TIMEOUT = 8   # seconds Twilio waits for student to speak before giving up
DTMF_TIMEOUT   = 10  # waiting time for keypad input
VOICE_CONFIG   = get_voice_config()

# poll timing
# ASYNC_POLL_PAUSE_SECONDS = gap between each poll check
# MAX_ASYNC_POLL_ATTEMPTS  = how many polls before we give up on this attempt
# total max wait = 3 * 20 = 60 seconds
# MAX_POLL_FAILURES = how many full timeouts before we end the call entirely
# without this limit, student could be stuck on hold forever if Ollama goes down
ASYNC_POLL_PAUSE_SECONDS = 3
MAX_ASYNC_POLL_ATTEMPTS  = 20
MAX_POLL_FAILURES        = 2  # hard exit after this many full timeouts

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

EXIT_PHRASES = {
    "bye", "goodbye", "ok bye", "okay bye",
    "thank you bye", "thanks bye", "that's all",
    "thats all", "no thank you", "no thanks",
    "band karo", "khatam karo", "bas", "bas karo"
}

# if a query contains any of these words, student must provide reg number first
# defined once here at module level — used in two places below so no duplication
PERSONAL_KEYWORDS = [
    "fee", "fees", "payment", "dues", "challan",
    "attendance", "absent", "present", "bunk",
    "result", "marks", "grade", "cgpa", "sgpa",
    "hostel", "room", "warden", "mess"
]

# words that count as yes or no when student is confirming a ticket
TICKET_YES = {"yes", "yeah", "haan", "ok", "okay", "sure", "please", "yes please", "yash", "1"}
TICKET_NO  = {"no", "nahi", "nope", "nah", "0"}


# INCOMING CALL
@router.post("/incoming")
async def incoming_call(
    request: Request,
    CallSid: str = Form(...)
):
    """
    Twilio hits this endpoint when student calls the helpline number.
    Clears any stale session, greets the student, starts listening.
    """
    logger.info(f"[Call] Incoming — CallSid: {CallSid}")

    # Fresh session — clears any leftover state from a previous call
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
    gather.say(random.choice(GREETING_LINES), **VOICE_CONFIG)
    response.append(gather)

    # if student says nothing after greeting, send to no-input handler
    response.redirect("/voice/no-input", method="POST")

    return Response(content=str(response), media_type="application/xml")


# PROCESS SPEECH
@router.post("/process")
async def process_speech_input(
    request: Request,
    CallSid: str      = Form(...),
    SpeechResult: str = Form(default=""),
    Confidence: str   = Form(default="0"),
    Digits: str       = Form(default=""),
):
    """
    Twilio sends STT result here after student speaks.

    Priority order:
    1. DTMF (keypad) input — most reliable, checked first
    2. Speech input       — cleaned and corrected by stt_handler
    3. Exit phrase check  — handled immediately, no background task
    4. OTP flow           — if awaiting_otp is set in session
    5. Ticket confirmation — if pending_ticket_issue is set in session
    6. Reg number capture — if query looks like a registration number
    7. Background AI task  — for everything else
    """
    confidence = float(Confidence) if Confidence else 0.0
    response   = VoiceResponse()
    session    = get_session(CallSid)

    # PRIORITY — if Digits received, use that directly
    # keypad is more reliable than speech, especially for numbers
    if Digits:
        query = Digits.replace("#", "").strip()
        logger.info(f"[Call] [{CallSid}] DTMF input: '{query}'")
    else:
        # Fall back to speech
        ok, result = process_speech(SpeechResult, confidence)
        if not ok:
            # STT failed or confidence too low — ask student to repeat
            gather = Gather(
                input="dtmf speech",
                action="/voice/process",
                method="POST",
                speech_timeout=SPEECH_TIMEOUT,
                language="en-IN",
                enhanced=True,
            )
            gather.say(
                "Sorry, I did not catch that. Please repeat or use your keypad.",
                **VOICE_CONFIG
            )
            response.append(gather)
            response.redirect("/voice/no-input", method="POST")
            return Response(content=str(response), media_type="application/xml")
        query = result

    # Student gave input — reset silence strike counter
    session["no_input_strikes"] = 0
    update_session(CallSid, session)

    logger.info(f"[Call] [{CallSid}] Query received: '{query}'")

    # EXIT CHECK — done here before any background task is launched
    # this means goodbye is instant — student doesn't wait 3+ seconds through polling
    # earlier this was inside _process_ai_background which caused a noticeable delay
    query_lower = query.strip().lower()
    if query_lower in EXIT_PHRASES:
        logger.info(f"[Call] [{CallSid}] Exit phrase detected: '{query}'")
        response.say("Thank you for calling the college helpline. Goodbye!", **VOICE_CONFIG)
        response.hangup()
        clear_session(CallSid)
        return Response(content=str(response), media_type="application/xml")

    # OTP VERIFICATION FLOW
    # if we are waiting for student to enter OTP, handle it before anything else
    # DTMF is preferred here since digits are more reliable via keypad
    if session.get("awaiting_otp"):
        otp = query.strip()
        if otp.isdigit() and len(otp) == 6:
            reg     = session.get("registration_number")
            success, reason = verify_otp_code(reg, otp)
            msg     = get_otp_message(reason)

            if success:
                session["awaiting_otp"] = False
                session["otp_verified"]  = True
                update_session(CallSid, session)
                logger.info(f"[Call] [{CallSid}] OTP verified for reg: {reg}")
            else:
                logger.info(f"[Call] [{CallSid}] OTP failed — reason: {reason}")

            _speak_and_listen(response, prepare_for_speech(msg))
            return Response(content=str(response), media_type="application/xml")
        else:
            # invalid OTP format — ask again
            _ask_for_digits(
                response,
                "Please enter your 6-digit OTP using the keypad and press hash when done.",
                num_digits=6
            )
            return Response(content=str(response), media_type="application/xml")

    # TICKET CONFIRMATION FLOW
    # if AI previously detected a complaint and asked yes/no, handle the reply here
    if session.get("pending_ticket_issue"):
        student_id = session.get("registration_number")

        # edge case: session lost the reg number, maybe due to timeout
        if not student_id:
            session.pop("pending_ticket_issue", None)
            update_session(CallSid, session)
            _ask_for_digits(
                response,
                "Sorry, I lost your details. Please enter your 8-digit registration number again.",
                num_digits=8
            )
            return Response(content=str(response), media_type="application/xml")

        confirmed = query.strip().lower()

        if confirmed in TICKET_YES:
            issue     = session.pop("pending_ticket_issue")
            update_session(CallSid, session)

            ticket_id = create_ticket(
                student_id=student_id,
                issue=issue,
                call_id=CallSid,
                category=None
            )

            if ticket_id:
                reply = (
                    f"Done. Your ticket number is {ticket_id}. "
                    f"Our team will contact you within 24 hours. "
                    f"Is there anything else I can help you with?"
                )
                logger.info(f"[Call] [{CallSid}] Ticket #{ticket_id} created for {student_id}")
            else:
                reply = "I am sorry, I could not register your complaint right now. Please try again."
                logger.error(f"[Call] [{CallSid}] Ticket creation failed for {student_id}")

            _speak_and_listen(response, prepare_for_speech(reply))
            return Response(content=str(response), media_type="application/xml")

        elif confirmed in TICKET_NO:
            session.pop("pending_ticket_issue", None)
            update_session(CallSid, session)
            reply = "Okay, no ticket raised. Is there anything else I can help you with?"
            _speak_and_listen(response, prepare_for_speech(reply))
            return Response(content=str(response), media_type="application/xml")

        else:
            # unclear response — student probably changed topic, drop the pending ticket
            # and let the query fall through to normal AI processing
            session.pop("pending_ticket_issue", None)
            update_session(CallSid, session)
            logger.info(f"[Call] [{CallSid}] Unclear ticket confirmation '{query}' — resuming normal flow")

    # REG NUMBER DETECTION
    # check if the student's input itself is a registration number
    # also resumes any query that was paused waiting for the reg number
    reg = None
    if query.isdigit() and len(query) == 8:
        reg = query
    else:
        reg = extract_registration_number(query)

    if reg and not session.get("registration_number"):
        student_data = get_student(reg)
        set_registration(CallSid, reg, student_data=student_data)
        session = get_session(CallSid)
        logger.info(f"[Call] [{CallSid}] Reg stored: {reg} | student_found={student_data is not None}")

        # if student was paused mid-query to give reg number, resume the original query now
        pending = pop_pending_query(CallSid)
        if pending:
            query = pending
            logger.info(f"[Call] [{CallSid}] Resuming pending query: '{query}'")

    # Ask for reg number if needed
    # if query needs personal data but reg number is not known yet, pause and ask
    needs_personal = any(w in query.lower() for w in PERSONAL_KEYWORDS)

    if needs_personal and not session.get("registration_number"):
        set_pending_query(CallSid, query)  # uses session handler
        _ask_for_digits(
            response,
            "Sure! Please enter your 8-digit registration number "
            "using the keypad and press hash when done.",
            num_digits=8
        )
        logger.info(f"[Call] [{CallSid}] Reg number requested for personal query: '{query}'")
        return Response(content=str(response), media_type="application/xml")

    # CALL AI BACKEND
    # check if a previous background task already finished while student was typing
    if CallSid in ASYNC_RESPONSES:
        ai_response = ASYNC_RESPONSES.pop(CallSid)

        if ai_response == "__EXIT__":
            response.say("Thank you for calling. Goodbye!", **VOICE_CONFIG)
            response.hangup()
            clear_session(CallSid)
            return Response(content=str(response), media_type="application/xml")

        clean_reply = prepare_for_speech(ai_response)
        _speak_and_listen(response, clean_reply)
        return Response(content=str(response), media_type="application/xml")

    # otherwise — start background task
    # reset poll counter, launch the AI task, play a wait message, redirect to /poll
    session["async_poll_attempts"] = 0
    session["poll_failure_count"]  = session.get("poll_failure_count", 0)
    update_session(CallSid, session)

    asyncio.create_task(_process_ai_background(CallSid, query))

    # immediate response — tell student to wait while AI works in background
    is_personal = any(w in query.lower() for w in PERSONAL_KEYWORDS)
    waiting_msg = (
        "Please wait while I check your information."
        if is_personal
        else "Please hold on for a moment."
    )
    _start_async_polling(response, waiting_msg)

    return Response(content=str(response), media_type="application/xml")


@router.post("/poll")
async def poll_async_response(CallSid: str = Form(...)):
    """Twilio polling loop for background AI responses."""
    response = VoiceResponse()
    session  = get_session(CallSid)

    # response is ready — serve it immediately
    if CallSid in ASYNC_RESPONSES:
        ai_response = ASYNC_RESPONSES.pop(CallSid)
        session["async_poll_attempts"] = 0
        update_session(CallSid, session)

        if ai_response == "__EXIT__":
            response.say("Thank you for calling the college helpline. Goodbye!", **VOICE_CONFIG)
            response.hangup()
            clear_session(CallSid)
            return Response(content=str(response), media_type="application/xml")

        clean_reply = prepare_for_speech(ai_response)
        _speak_and_listen(response, clean_reply)
        return Response(content=str(response), media_type="application/xml")

    # still waiting — keep counting poll attempts
    attempts = int(session.get("async_poll_attempts", 0)) + 1
    session["async_poll_attempts"] = attempts
    update_session(CallSid, session)

    # poll limit hit — AI took too long on this attempt
    if attempts >= MAX_ASYNC_POLL_ATTEMPTS:
        failure_count = int(session.get("poll_failure_count", 0)) + 1
        session["poll_failure_count"]  = failure_count
        session["async_poll_attempts"] = 0
        update_session(CallSid, session)

        logger.warning(
            f"[Call] [{CallSid}] Poll timeout — "
            f"attempt {failure_count}/{MAX_POLL_FAILURES}"
        )

        # hard exit — Ollama is probably down, end the call cleanly
        if failure_count >= MAX_POLL_FAILURES:
            logger.error(f"[Call] [{CallSid}] Max poll failures reached — ending call")
            response.say(
                "I am sorry, the system is currently unavailable. "
                "Please call again shortly. Goodbye!",
                **VOICE_CONFIG
            )
            response.hangup()
            clear_session(CallSid)
            return Response(content=str(response), media_type="application/xml")

        # soft timeout — tell student to try asking again
        _speak_and_listen(
            response,
            "I need a little more time to check this. Please ask again in a moment."
        )
        session["async_poll_attempts"] = 0
        update_session(CallSid, session)
        return Response(content=str(response), media_type="application/xml")

    # still within limits — keep polling
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
    CallSid:    str = Form(...),
    CallStatus: str = Form(...),
):
    """Twilio calls this when call ends."""
    logger.info(f"[Call] [{CallSid}] Status: {CallStatus}")

    if CallStatus in ("completed", "failed", "busy", "no-answer"):
        # clean up leftover background response if poll never picked it up
        ASYNC_RESPONSES.pop(CallSid, None)
        clear_session(CallSid)

    return Response(content="", media_type="text/plain")


# HELPERS

# If AI response already ends with a question, don't add a redundant prompt.
# for example if AI says "anything else?" we should not play a followup line on top
# that would make two questions play back to back which sounds broken to the student
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
        input="dtmf speech",
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
# used for reg number (8 digits) and OTP (6 digits) collection
# student can press # to submit early, or enter all digits and it auto-submits
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
) -> str:
    # sends the student query to the /query endpoint in main.py
    # that endpoint runs all guards and calls Ollama, then returns the AI answer
    # call_sid is passed so main.py logs can be correlated back to this Twilio call
    try:
        payload = {
            "query":               query,
            "call_sid":            call_sid,      # now accepted by main.py QueryRequest
            "chat_history":        chat_history,
            "registration_number": registration_number,
        }

        async with httpx.AsyncClient(timeout=90.0) as client:  # timeout time increased
            resp = await client.post(BACKEND_QUERY_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("answer", "").strip()

            if not answer:
                logger.warning(f"[AI] [{call_sid}] Empty answer received from backend")
                return "I am sorry, I could not generate a response. Please try again."

            logger.info(f"[AI] [{call_sid}] Response received: '{answer[:80]}'")
            return answer

    except httpx.TimeoutException:
        logger.error(f"[AI] [{call_sid}] Backend timeout after 90s")
        return "I am sorry, it is taking too long to get a response. Please try again."
    except httpx.ConnectError:
        logger.error(f"[AI] [{call_sid}] Cannot connect to backend — is uvicorn running?")
        return "I am sorry, the system is temporarily unavailable. Please try again shortly."
    except Exception as e:
        logger.error(f"[AI] [{call_sid}] Unexpected error: {e}", exc_info=True)
        return "I am sorry, I am having trouble right now. Please try again."


# background ai worker
# runs as a separate async task so Twilio does not time out while waiting for Ollama
# writes the final response to ASYNC_RESPONSES once done
# the /poll endpoint keeps checking that dict and serves the response when it appears
async def _process_ai_background(call_sid: str, query: str) -> None:
    # always re-fetch session inside background task
    # never rely on a session reference passed from outside
    # by the time this task runs, the original dict may already be stale
    session    = get_session(call_sid)
    student_id = session.get("registration_number")

    # STEP 1: Detect if this is a PROBLEM or a QUERY
    # detect_intent checks if student is reporting something broken (needs ticket)
    # or just asking for information (AI can answer directly)
    intent_result = detect_intent(query)
    logger.info(
        f"[BG] [{call_sid}] Intent: {intent_result['intent']} | "
        f"category: {intent_result['category']} | "
        f"needs_ticket: {intent_result['needs_ticket']}"
    )

    # STEP 2: Route based on intent
    if intent_result["needs_ticket"]:

        if student_id:
            # student is identified — ask for confirmation before raising ticket
            ai_response = (
                "I understand you are facing an issue. "
                "I can raise a support ticket and the respective department "
                "will contact you within 24 hours. "
                "Please say yes to confirm or no to cancel. "
                "You can also press 1 for yes or 0 for no."
            )
            # Store pending ticket intent so next response can create it
            session = get_session(call_sid)
            session["pending_ticket_issue"] = query
            update_session(call_sid, session)
            logger.info(f"[BG] [{call_sid}] Ticket confirmation requested for: '{query[:60]}'")

        else:
            # student not identified yet — need reg number before raising ticket
            ai_response = (
                "I would like to help you with that. "
                "Please enter your 8-digit registration number "
                "on the keypad so I can raise a ticket for you."
            )
            logger.info(f"[BG] [{call_sid}] Reg number requested before ticket creation")

    else:
        # STEP 3: It's a QUERY → call AI normally
        ai_response = await _call_ai(
            query=query,
            call_sid=call_sid,
            chat_history=session.get("chat_history", []),
            registration_number=student_id,
        )

    # STEP 4: Update chat history
    # capped at last 10 messages (5 turns) to stay within model context window
    session = get_session(call_sid)
    history = session.get("chat_history", [])
    history.append({"role": "user",      "content": query})
    history.append({"role": "assistant", "content": ai_response})
    session["chat_history"] = history[-10:]
    update_session(call_sid, session)

    # STEP 5: Store response for poll pickup
    ASYNC_RESPONSES[call_sid] = ai_response
    logger.info(f"[BG] [{call_sid}] Response stored for poll pickup")