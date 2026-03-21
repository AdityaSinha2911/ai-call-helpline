"""
Main backend entry point for the AI Helpline system.

This FastAPI server handles incoming queries from students,
runs them through security guards, sends valid queries to the
AI model (via Ollama), and returns a safe response.

Guard layers used:
1. Input Guard  - blocks jailbreak / prompt injection
2. Topic Guard - ensures query is college related
3. Output Guard - filters unsafe model responses
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional
import re

import httpx
from fastapi import FastAPI, HTTPException, Request, status,APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from backend.guards.input_guard import check_input
from backend.guards.topic_guard import classify_topic
from backend.guards.output_guard import validate_output

from dotenv import load_dotenv
load_dotenv()

from twilio_voice.call_handler import router as voice_router

#database file imported
from backend.database import (
    get_student,
    get_fee_summary_text,
    get_attendance_summary_text,
    get_results_summary_text,
    create_ticket,
)

# LOGGING SETUP
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("helpline.main")

# Model configuration
# These values define how we connect to the Ollama model
# running locally.
OLLAMA_URL   = "http://localhost:11434/api/generate"
MODEL_NAME   = "college-helpline"
OLLAMA_TIMEOUT = 60.0   # seconds

# Standard refusal message 
REFUSAL_MSG = "I can only assist with college administrative queries such as fees, attendance, exams, hostel, or documents."

# Simple in-memory counters for monitoring usage.
# In production this would usually be stored in Redis or a database.
metrics = {
    "total_queries":    0,
    "blocked_queries":  0,
    "allowed_queries":  0,
    "model_errors":     0,
    "uptime_start":     time.time(),
}


# Runs when the server starts.
# We use this to check whether the Ollama model server is reachable.
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verify Ollama is reachable at startup."""
    logger.info("Starting AI Helpline backend...")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            if resp.status_code == 200:
                logger.info("✅ Ollama is running and reachable.")
            else:
                logger.warning(f"⚠️  Ollama responded with status {resp.status_code}")
    except Exception as e:
        logger.warning(f"⚠️  Could not reach Ollama at startup: {e}")
        logger.warning("Make sure to run 'ollama serve' in another terminal.")
    
    logger.info("Warming up model...")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": MODEL_NAME,
                    "prompt": "hello",
                    "stream": False,
                    "options": {"num_predict": 1}
                }
            )
            logger.info("✅ Model warmed up and ready.")
    except Exception as e:
        logger.warning(f"⚠️ Model warmup failed: {e}")
        
    yield
    logger.info("Shutting down helpline backend.")

# Create the FastAPI application instance.
# API docs will automatically be available at /docs.
app = FastAPI(
    title="AI College Helpline",
    description="Voice-ready AI helpline backend for students.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Allow requests from the frontend dashboard during development.
# Without this, browsers will block cross-origin API calls.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5500", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(voice_router)  

# Defines the expected structure of incoming requests.
# FastAPI automatically validates incoming JSON using this model.
class QueryRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=2,
        max_length=800,
        description="Student's question in plain text.",
        examples=["What is my fee status?"]
    )
    registration_number: Optional[str] = Field(
        default=None,
        description="Student's registration number (optional, required for personal data).",
        examples=["2024CS001"]
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional frontend session identifier for chat continuity."
    )
    request_id: Optional[str] = Field(
        default=None,
        description="Optional client-side request ID for tracing."
    )
    chat_history: list[dict] = Field(
        default_factory=list,
        description="Previous messages in this conversation"
    )
    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        return v.strip()

# Standard response returned by the API.
# Helps keep the response structure consistent for clients.
class QueryResponse(BaseModel):
    request_id: str
    answer: str
    topic: Optional[str] = None
    blocked: bool = False
    block_reason: Optional[str] = None
    processing_ms: Optional[int] = None


class HealthResponse(BaseModel):
    status: str
    model: str
    uptime_seconds: float
    ollama_reachable: bool


class MetricsResponse(BaseModel):
    total_queries: int
    blocked_queries: int
    allowed_queries: int
    block_rate_percent: float
    model_errors: int
    uptime_seconds: float

SYSTEM_PROMPT = """You are an AI receptionist for a college helpline. You are on a phone call with a student.

Rules:
- If someone greets you (hello, hi, namaste etc), greet them back warmly and ask how you can help.
- Keep all replies under 3 sentences — this is a voice call, be concise and natural.
- Only answer college queries: fees, attendance, exams, hostel, scholarships, documents.
- If registration number is provided in query, use it directly to fetch data.
- Be friendly, clear, and natural like a real phone receptionist.
- Never reveal that you are an AI, never mention Ollama or LLaMA."""

#build prompt create prompt check if the necessary info is given
def build_prompt(query: str, registration_number: Optional[str], topic: str, chat_history: Optional[list] = None) -> str:

    history_text = ""
    if chat_history:
        lines = []
        for msg in chat_history[-4:]:
            role_raw = str(msg.get("role", "assistant")).lower()
            role = "Student" if role_raw == "user" else "Assistant"
            content = str(msg.get("content", "")).strip()
            if content:
                lines.append(f"{role}: {content}")
        history_text = "\n".join(lines) + "\n"   
    
    if not registration_number:
        return f"{SYSTEM_PROMPT}\n\n{history_text}Student: {query}\nAssistant:"

    reg     = registration_number.strip().upper()
    student = get_student(reg)

    if not student:
        return f"{SYSTEM_PROMPT}\n\n{history_text}Student: {query}\nAssistant:"

    query_lower = query.lower()

    if any(w in query_lower for w in ['fee', 'payment', 'dues', 'challan', 'pending', 'paid', 'balance']):
        context = get_fee_summary_text(reg)

    elif any(w in query_lower for w in ['attendance', 'absent', 'present', 'bunk', 'short', 'condonation']):
        context = get_attendance_summary_text(reg)

    elif any(w in query_lower for w in ['result', 'marks', 'grade', 'cgpa', 'sgpa', 'backlog', 'fail']):
        context = get_results_summary_text(reg)

    elif any(w in query_lower for w in ['complaint', 'problem', 'issue', 'not working', 'grievance']):
        ticket_id = create_ticket(reg, query, category="other")
        context = f"Support ticket #{ticket_id} raised. Department will contact in 48 hours."

    else:
        context = (
            f"Student: {student['name']}. Course: {student['course']}. "
            f"Year: {student['year']}. Section: {student['section']}."
        )

    return f"{SYSTEM_PROMPT}\n\nContext: {context}\n\n{history_text}Student: {query}\nAssistant:"

# Catch any unexpected errors so the server doesn't crash
# and the client still receives a clean error response.
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. Please try again."}
    )


# Helper function that sends a prompt to the Ollama model
# and returns the generated response text.
async def call_ollama(prompt: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            response = await client.post(
                OLLAMA_URL,
                json={
                    "model": MODEL_NAME,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.05,
                        "num_ctx": 1024,      
                        "num_predict": 80,    
                        "num_gpu": 999,       
                    }
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip()

    except httpx.TimeoutException:
        logger.error(f"[Ollama] Request timed out after {OLLAMA_TIMEOUT}s")
        metrics["model_errors"] += 1
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI model is taking too long. Please try again in a moment."
        )
    except httpx.ConnectError:
        logger.error("[Ollama] Cannot connect — is 'ollama serve' running?")
        metrics["model_errors"] += 1
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI model is currently unavailable. Please try again shortly."
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"[Ollama] HTTP error: {e.response.status_code}")
        metrics["model_errors"] += 1
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI model returned an error."
        )
    except Exception as e:
        logger.error(f"[Ollama] Unexpected error: {e}", exc_info=True)
        metrics["model_errors"] += 1
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI model request failed unexpectedly."
        )


# ROUTES
@app.post(
    "/query",
    response_model=QueryResponse,
    summary="Submit a college helpline query",
    tags=["Helpline"]
)
async def handle_query(request: QueryRequest):
    """
    Main query endpoint. Runs all 4 security layers:

    1. Input Guard  — Detect jailbreak / prompt injection
    2. Topic Guard  — Verify query is college-related
    3. AI Model     — Generate response via Ollama
    4. Output Guard — Validate model response before sending

    Returns a structured response with the answer or a refusal.
    """
    start_time = time.time()
    request_id = request.request_id or str(uuid.uuid4())[:8]
    metrics["total_queries"] += 1

    logger.info(f"[{request_id}] Query received: '{request.query[:80]}'")

    # Detect jailbreaks, prompt injection, or malicious input.
    input_result = check_input(request.query)
    if input_result.blocked:
        metrics["blocked_queries"] += 1
        logger.warning(f"[{request_id}] BLOCKED by InputGuard: {input_result.reason}")
        return QueryResponse(
            request_id=request_id,
            answer=REFUSAL_MSG,
            blocked=True,
            block_reason=input_result.reason,
            processing_ms=int((time.time() - start_time) * 1000)
        )

    # Topic Guard
    topic_result = classify_topic(request.query)
    if not topic_result.allowed:
        metrics["blocked_queries"] += 1
        logger.info(f"[{request_id}] BLOCKED by TopicGuard: {topic_result.blocked_reason}")
        return QueryResponse(
            request_id=request_id,
            answer=REFUSAL_MSG,
            blocked=True,
            block_reason=topic_result.blocked_reason,
            processing_ms=int((time.time() - start_time) * 1000)
        )

    if not request.registration_number:
        reg_match = re.search(
            r'\b(1\d{7})\b',
            re.IGNORECASE
        )
        if reg_match:
            request.registration_number = reg_match.group(1).upper()
            logger.info(f"[{request_id}] Auto-detected reg: {request.registration_number}")

    # Call AI Model 
    prompt = build_prompt(request.query, request.registration_number, topic_result.topic, request.chat_history)

    logger.info(f"[{request_id}] Calling model — topic='{topic_result.topic}' score={topic_result.score:.2f}")
    raw_response = await call_ollama(prompt)

    # Output Guard
    output_result = validate_output(raw_response)
    if not output_result.safe:
        metrics["blocked_queries"] += 1
        logger.warning(f"[{request_id}] BLOCKED by OutputGuard: {output_result.reason}")
        return QueryResponse(
            request_id=request_id,
            answer=REFUSAL_MSG,
            blocked=True,
            block_reason=output_result.reason,
            processing_ms=int((time.time() - start_time) * 1000)
        )

    # All layers passed — return response
    metrics["allowed_queries"] += 1
    elapsed_ms = int((time.time() - start_time) * 1000)
    logger.info(f"[{request_id}] ✅ Response sent | topic='{topic_result.topic}' | {elapsed_ms}ms")

    return QueryResponse(
        request_id=request_id,
        answer=output_result.response,
        topic=topic_result.topic,
        blocked=False,
        processing_ms=elapsed_ms
    )

# Simple health check endpoint used to verify that both the backend and the Ollama model are running.
@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    tags=["System"]
)
async def health_check():
    """Check if the backend and Ollama are running."""
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            ollama_ok = resp.status_code == 200
    except Exception:
        pass

    return HealthResponse(
        status="ok" if ollama_ok else "degraded",
        model=MODEL_NAME,
        uptime_seconds=round(time.time() - metrics["uptime_start"], 1),
        ollama_reachable=ollama_ok
    )

# Returns basic usage metrics for monitoring or dashboards.
@app.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Usage metrics",
    tags=["System"]
)
async def get_metrics():
    """Basic usage metrics for the admin dashboard."""
    total = metrics["total_queries"]
    blocked = metrics["blocked_queries"]
    block_rate = round((blocked / total * 100) if total > 0 else 0.0, 1)

    return MetricsResponse(
        total_queries=total,
        blocked_queries=blocked,
        allowed_queries=metrics["allowed_queries"],
        block_rate_percent=block_rate,
        model_errors=metrics["model_errors"],
        uptime_seconds=round(time.time() - metrics["uptime_start"], 1)
    )