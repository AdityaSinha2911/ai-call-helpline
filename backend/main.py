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
import asyncio

import httpx
from fastapi import FastAPI, HTTPException, Request, status,APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from backend.guards.input_guard import check_input
from backend.guards.topic_guard import classify_topic
from backend.guards.output_guard import validate_output

# RAG engine — retrieves relevant college knowledge chunks for any query
# Sits between topic guard and prompt builder
from backend.rag.rag_engine import load_and_index_documents, retrieve_context

from dotenv import load_dotenv
load_dotenv()

from twilio_voice.call_handler import router as voice_router

#database file imported
from backend.database import (
    get_student,
    get_fee_summary_text,
    get_attendance_summary_text,
    get_results_summary_text,get_hostel_summary_text,
    create_ticket,get_all_tickets, close_ticket,
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
OLLAMA_TIMEOUT = 120.0   # seconds

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

_ollama_semaphore = asyncio.Semaphore(1)

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

    # ── RAG INDEXING ──────────────────────────────────────────────────────────
    # Load and index all .txt files from backend/rag/knowledge_base/ into
    # ChromaDB. This runs in a thread executor so it does NOT block the
    # async event loop (indexing can take 2-5 seconds on first run).
    # On subsequent restarts, if documents haven't changed, it skips
    # re-indexing instantly (hash-based smart cache).
    # If knowledge_base/ folder is missing, RAG is silently disabled —
    # the system continues working normally without it.
    logger.info("Indexing RAG knowledge base...")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, load_and_index_documents)
        logger.info("✅ RAG knowledge base ready.")
    except Exception as e:
        # RAG failure must NEVER crash startup — graceful degradation
        logger.warning(f"⚠️ RAG indexing failed (system will run without RAG): {e}")
        
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

class TicketCreateRequest(BaseModel):
    student_id: str           # registration number
    issue: str                # what student described
    call_id: Optional[str]    # Twilio CallSid
    priority: Optional[str] = "Normal"

class TicketCloseRequest(BaseModel):
    ticket_id: int
    admin_note: Optional[str] = ""

SYSTEM_PROMPT = """You are an AI receptionist for a college helpline. You are on a phone call with a student.

STRICT RULES — follow every one:
- Reply in MAXIMUM 2 sentences. Never more. This is a voice call — brevity is critical.
- If data is given in Context, read it and summarize in ONE short sentence. Do not list every field.
- If someone greets you, reply in ONE sentence and ask how you can help.
- Only answer college queries: fees, attendance, exams, hostel, scholarships, documents, library.
- If registration number is provided in the query, use it directly.
- Be friendly and natural like a real phone receptionist.
- Never reveal that you are an AI, never mention Ollama or LLaMA.
- Never start your response with "I" — vary your sentence starters."""

#build prompt create prompt check if the necessary info is given
def build_prompt(query: str, registration_number: Optional[str], topic: str, chat_history: Optional[list] = None) -> str:
    """
    Constructs the final prompt sent to Ollama.

    Injection order (matters for model attention — most important last):
        1. SYSTEM instructions       — how the model should behave
        2. RAG CONTEXT               — general college knowledge (policies, rules, FAQs)
        3. STUDENT DATA              — live personal data from DB (fees, attendance etc.)
        4. CONVERSATION HISTORY      — last 4 turns for multi-turn awareness
        5. STUDENT QUERY             — what the student asked right now

    RAG runs on EVERY query regardless of registration number.
    It retrieves relevant knowledge chunks from ChromaDB using
    semantic similarity — so "scholarship deadline" will find
    the scholarship policy even if the student didn't use exact words.

    If RAG finds nothing relevant, the [COLLEGE KNOWLEDGE] section
    is simply omitted — no effect on existing behavior.
    """

    # Build conversation history (last 4 messages only to keep prompt short)
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

    logger.info(f"[DEBUG] build_prompt called — reg={registration_number}, query={query}")

    # RAG: retrieve relevant knowledge for this query
    # retrieve_context() embeds the query, searches ChromaDB, and returns
    # the top matching chunks filtered by relevance threshold.
    # Returns empty string if nothing relevant found (graceful degradation).
    rag_context = retrieve_context(query)

    # Case 1: No registration number — general query
    if not registration_number:
        prompt = SYSTEM_PROMPT

        # Inject RAG knowledge only if something relevant was found
        if rag_context:
            prompt += f"\n\n[COLLEGE KNOWLEDGE]\n{rag_context}"
            logger.info("[RAG] Context injected into prompt (no-reg path).")

        prompt += f"\n\n{history_text}Student: {query}\nAssistant:"
        return prompt

    # Case 2: Registration number provided — fetch personal DB data
    reg     = registration_number.strip().upper()
    student = get_student(reg)
    logger.info(f"[DEBUG] get_student result — {student}")

    # Student not found in DB — fall back to general response with RAG
    if not student:
        prompt = SYSTEM_PROMPT

        if rag_context:
            prompt += f"\n\n[COLLEGE KNOWLEDGE]\n{rag_context}"
            logger.info("[RAG] Context injected into prompt (student-not-found path).")

        prompt += f"\n\n{history_text}Student: {query}\nAssistant:"
        return prompt

    query_lower = query.lower()

    # Fetch the right DB context based on query intent
    # These keyword checks determine which DB table to query.
    # RAG runs separately and is COMBINED with this DB data.
    if any(w in query_lower for w in ['fee', 'payment', 'dues', 'challan', 'pending', 'paid', 'balance']):
        db_context = get_fee_summary_text(reg)
        logger.info(f"[DEBUG] Context being sent to AI: {db_context}")

    elif any(w in query_lower for w in ['attendance', 'absent', 'present', 'bunk', 'short', 'condonation']):
        db_context = get_attendance_summary_text(reg)
        logger.info(f"[DEBUG] Context being sent to AI: {db_context}")

    elif any(w in query_lower for w in ['result', 'marks', 'grade', 'cgpa', 'sgpa', 'backlog', 'fail']):
        db_context = get_results_summary_text(reg)

    elif any(w in query_lower for w in ['hostel', 'room allot', 'hostel allot', 'accommodation', 'warden', 'mess', 'laundry']):
        db_context = get_hostel_summary_text(reg)
        logger.info(f"[DEBUG] Hostel context built for: {reg}")

    elif any(w in query_lower for w in ['complaint', 'problem', 'issue', 'not working', 'grievance']):
        db_context = "Student has reported an issue. A support ticket will be raised for them."

    else:
        db_context = (
            f"Student: {student['name']}. Course: {student['course']}. "
            f"Year: {student['year']}. Section: {student['section']}."
        )

    # Assemble final prompt
    # Order: SYSTEM -> RAG (general) -> DB (personal) -> History -> Query
    # This ordering is intentional:
    #   - System sets behavior rules
    #   - RAG provides general college policy knowledge
    #   - DB provides specific personal data (overrides generic with real data)
    #   - History provides conversation continuity
    #   - Query is what the model responds to
    prompt = SYSTEM_PROMPT

    if rag_context:
        # General college knowledge from documents (scholarship rules, hostel timings etc.)
        prompt += f"\n\n[COLLEGE KNOWLEDGE]\n{rag_context}"
        logger.info("[RAG] Context injected into prompt (registered student path).")

    # Personal live data from DB
    prompt += f"\n\nContext: {db_context}"

    # Conversation history + current query
    prompt += f"\n\n{history_text}Student: {query}\nAssistant:"

    return prompt

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
    async with _ollama_semaphore:
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
                response = await client.post(
                    OLLAMA_URL,
                    json={
                        "model": MODEL_NAME,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3, 
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
    from twilio_voice.stt_handler import clean_speech
    request.query = clean_speech(request.query)

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

    HARD_BLOCK_PATTERNS = [
    r'\b(ipl|fifa|nba|match|won|winner|champion)\b',
    r'\b(recipe|cook|biryani|food|restaurant)\b',
    r'\b(politics|government|election|minister|bjp|congress)\b',
    r'\b(movie|film|actor|actress|song|music)\b',
        ]
    
    import re as _re
    query_lower_check = request.query.lower()
    for pattern in HARD_BLOCK_PATTERNS:
        if _re.search(pattern, query_lower_check):
            metrics["blocked_queries"] += 1
            logger.info(f"[{request_id}] BLOCKED by hard-block pattern: {pattern}")
            return QueryResponse(
                request_id=request_id,
                answer=REFUSAL_MSG,
                blocked=True,
                block_reason="off_topic_hard_block",
                processing_ms=int((time.time() - start_time) * 1000)
            )
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
        # 8-digit numeric reg number
        reg_match = re.search(r'\b(\d{8})\b', request.query)
        if reg_match:
            request.registration_number = reg_match.group(1)
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

# ticket generation
@app.post("/create-ticket")
def create_ticket_route(data: TicketCreateRequest):
    """
    Called after OTP verification when AI detects a PROBLEM.
    Creates ticket and returns ticket ID to read back to student.
    """
    # Auto-detect category from issue text (your existing logic in create_ticket handles this)
    ticket_id = create_ticket(
        student_id=data.student_id,
        issue=data.issue,
        call_id=data.call_id,
        priority=data.priority
    )
    
    if ticket_id:
        return {
            "success": True,
            "ticket_id": ticket_id,
            "message": f"Your complaint has been registered. Ticket number is {ticket_id}. Our team will contact you within 24 hours."
        }
    else:
        return {"success": False, "message": "Failed to create ticket. Please try again."}


@app.get("/admin/tickets")
def admin_get_tickets(status: str = None, limit: int = 50):
    """
    Admin dashboard fetches all tickets.
    Optional filter: ?status=Open or ?status=Closed
    """
    tickets = get_all_tickets(status=status, limit=limit)
    return tickets


@app.post("/admin/close-ticket")
def admin_close_ticket(data: TicketCloseRequest):
    success = close_ticket(
        ticket_id=data.ticket_id,
        admin_note=data.admin_note
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Ticket #{data.ticket_id} not found")
    return {"message": f"Ticket #{data.ticket_id} closed", "status": "success"}


@app.get("/admin/ticket-stats")
def ticket_stats():
    """
    For dashboard summary cards —
    total open, in-progress, closed counts by category.
    """
    all_tickets = get_all_tickets()
    
    stats = {
        "total": len(all_tickets),
        "open": len([t for t in all_tickets if t["status"] == "Open"]),
        "in_progress": len([t for t in all_tickets if t["status"] == "In Progress"]),
        "closed": len([t for t in all_tickets if t["status"] == "Closed"]),
        "by_category": {}
    }
    
    for ticket in all_tickets:
        cat = ticket["category"]
        stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
    
    return stats

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