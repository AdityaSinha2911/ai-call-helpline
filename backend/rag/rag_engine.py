"""
rag_engine.py — Production-Grade RAG Engine
=============================================
Handles: document loading, chunking, embedding, indexing, retrieval.

Architecture:
    knowledge_base/*.txt
        → chunk_text()
        → SentenceTransformer embeds
        → ChromaDB stores
        → retrieve_context(query) → relevant chunks → injected into prompt

Design decisions:
    - Persistent ChromaDB on disk (survives restarts, no re-indexing every time)
    - Relevance threshold filter (irrelevant chunks blocked)
    - Graceful degradation (if RAG fails, system continues without it)
    - Thread-safe (ChromaDB handles concurrent reads)
    - Singleton pattern (model loaded once at module level)
"""

import os
import logging
import hashlib
import json
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

# LOGGING
logger = logging.getLogger(__name__)

# PATHS  (relative to this file's location)
RAG_DIR          = Path(__file__).parent                        # backend/rag/
KNOWLEDGE_DIR    = RAG_DIR / "knowledge_base"                   # backend/rag/knowledge_base/
CHROMA_PERSIST   = RAG_DIR / "chroma_store"                     # backend/rag/chroma_store/  (auto-created)
HASH_CACHE_FILE  = RAG_DIR / "index_hash.json"                  # tracks if re-index needed


# CONFIG

COLLECTION_NAME      = "college_knowledge"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"  
CHUNK_SIZE           = 400                    # characters per chunk
CHUNK_OVERLAP        = 80                     # overlap between consecutive chunks
TOP_K                = 3                      # how many chunks to retrieve per query
RELEVANCE_THRESHOLD  = 0.70                   # cosine distance cutoff (lower = stricter)
 # 0 = identical, 1 = unrelated


# SINGLETON: embedding model + chroma client
# Loaded ONCE when module is first imported.

logger.info("[RAG] Loading SentenceTransformer model: %s", EMBEDDING_MODEL_NAME)
_embedding_model: SentenceTransformer = SentenceTransformer(EMBEDDING_MODEL_NAME)

_chroma_client = chromadb.PersistentClient(
    path=str(CHROMA_PERSIST),
    settings=Settings(anonymized_telemetry=False)
)
_collection = _chroma_client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"}   # cosine similarity for semantic search
)

logger.info("[RAG] ChromaDB collection '%s' ready. Docs stored: %d",
            COLLECTION_NAME, _collection.count())



# INTERNAL HELPERS


def _chunk_text(text: str) -> list[str]:
    """
    Splits a large text into overlapping chunks.

    Why overlap?
        If a sentence spans two chunk boundaries, overlap ensures
        the context is not lost at the split point.

    Example (chunk_size=10, overlap=3):
        text   = "AAAAABBBBBCCCCC"
        chunks = ["AAAAABBBBB", "BBBBBCCCCC"]
    """
    chunks: list[str] = []
    start = 0
    text = text.strip()
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


def _compute_corpus_hash() -> str:
    """
    Computes a combined MD5 hash of ALL documents in knowledge_base/.
    Used to detect if re-indexing is needed after file changes.
    """
    if not KNOWLEDGE_DIR.exists():
        return ""
    hasher = hashlib.md5()
    for filepath in sorted(KNOWLEDGE_DIR.glob("*.txt")):
        hasher.update(filepath.read_bytes())
    return hasher.hexdigest()


def _load_hash_cache() -> str:
    """Returns previously stored hash, or empty string if none."""
    if HASH_CACHE_FILE.exists():
        try:
            return json.loads(HASH_CACHE_FILE.read_text()).get("hash", "")
        except Exception:
            return ""
    return ""


def _save_hash_cache(hash_value: str) -> None:
    HASH_CACHE_FILE.write_text(json.dumps({"hash": hash_value}))



# PUBLIC API

def load_and_index_documents(force: bool = False) -> None:
    """
    Loads all .txt files from knowledge_base/, chunks them,
    embeds them, and stores in ChromaDB.

    Smart re-indexing:
        - Computes hash of all documents.
        - If hash matches previous run → skips re-indexing (fast startup).
        - If documents changed → re-indexes automatically.
        - Use force=True to always re-index.

    Called once at FastAPI startup.
    """
    if not KNOWLEDGE_DIR.exists():
        logger.warning("[RAG] knowledge_base/ not found at %s. RAG will be disabled.", KNOWLEDGE_DIR)
        return

    # Smart re-index check 
    current_hash = _compute_corpus_hash()
    cached_hash  = _load_hash_cache()

    if not force and current_hash == cached_hash and _collection.count() > 0:
        logger.info("[RAG] Documents unchanged. Skipping re-index. (%d chunks in DB)", _collection.count())
        return

    logger.info("[RAG] New or changed documents detected. Starting indexing...")

    # Clear old data 
    existing_ids = _collection.get(include=[])["ids"]
    if existing_ids:
        _collection.delete(ids=existing_ids)
        logger.info("[RAG] Cleared %d old chunks.", len(existing_ids))

    # Load + chunk all documents 
    all_documents: list[str] = []
    all_ids:       list[str] = []
    all_metadata:  list[dict] = []

    txt_files = list(KNOWLEDGE_DIR.glob("*.txt"))
    if not txt_files:
        logger.warning("[RAG] No .txt files found in knowledge_base/. RAG disabled.")
        return

    for filepath in txt_files:
        try:
            text   = filepath.read_text(encoding="utf-8").strip()
            chunks = _chunk_text(text)
            logger.info("[RAG] %s → %d chunks", filepath.name, len(chunks))

            for idx, chunk in enumerate(chunks):
                chunk_id = f"{filepath.stem}_chunk_{idx}"
                all_documents.append(chunk)
                all_ids.append(chunk_id)
                all_metadata.append({
                    "source":      filepath.name,
                    "chunk_index": idx,
                    "total_chunks": len(chunks)
                })
        except Exception as e:
            logger.error("[RAG] Failed to process %s: %s", filepath.name, e)
            continue

    if not all_documents:
        logger.warning("[RAG] No chunks generated. Check your .txt files.")
        return

    #  Embed all chunks (batched)
    logger.info("[RAG] Embedding %d chunks...", len(all_documents))
    embeddings = _embedding_model.encode(
        all_documents,
        batch_size=64,
        show_progress_bar=False,
        convert_to_numpy=True
    ).tolist()

    # Store in ChromaDB 
    _collection.upsert(
        documents=all_documents,
        embeddings=embeddings,
        ids=all_ids,
        metadatas=all_metadata
    )

    _save_hash_cache(current_hash)
    logger.info("[RAG] Indexing complete. %d chunks stored in ChromaDB.", len(all_documents))


def retrieve_context(query: str, top_k: int = TOP_K) -> str:
    """
    Retrieves the most semantically relevant chunks for a given query.

    Args:
        query:  The student's spoken query (already STT-corrected).
        top_k:  Number of chunks to retrieve.

    Returns:
        A single string of relevant context to inject into the LLM prompt.
        Returns empty string if nothing relevant found (graceful degradation).

    Flow:
        query → embed → cosine search in ChromaDB → filter by threshold → join
    """

    PERSONAL_INDICATORS = ["meri ", "mera ", "mere ", "my "]
    PERSONAL_TOPICS = ["fees", "attendance", "result", "cgpa", "hostel room", "marks", "backlog", "scholarship amount"]
    
    query_lower = query.lower()
    is_personal = (
        any(ind in query_lower for ind in PERSONAL_INDICATORS) and
        any(t in query_lower for t in PERSONAL_TOPICS)
    )
    
    if is_personal:
        logger.debug("[RAG] Personal query detected — skipping RAG: '%s'", query[:60])
        return ""
    if _collection.count() == 0:
        logger.debug("[RAG] Collection empty. No context retrieved.")
        return ""

    if not query or not query.strip():
        return ""

    try:
        query_embedding = _embedding_model.encode([query.strip()]).tolist()

        results = _collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k, _collection.count()),
            include=["documents", "metadatas", "distances"]
        )

        raw_docs      = results.get("documents", [[]])[0]
        raw_distances = results.get("distances",  [[]])[0]
        raw_meta      = results.get("metadatas",  [[]])[0]

        # Relevance filtering 
        # Only keep chunks below the distance threshold.
        # Cosine distance: 0.0 = identical, 1.0 = completely unrelated.
        filtered_chunks: list[str] = []
        for doc, dist, meta in zip(raw_docs, raw_distances, raw_meta):
            if dist <= RELEVANCE_THRESHOLD:
                filtered_chunks.append(doc)
                logger.debug("[RAG] Accepted chunk (dist=%.3f) from '%s'", dist, meta.get("source"))
            else:
                logger.debug("[RAG] Rejected chunk (dist=%.3f) — below threshold", dist)

        if not filtered_chunks:
            logger.info("[RAG] No relevant chunks found for query: '%s'", query[:60])
            return ""

        context = "\n---\n".join(filtered_chunks)
        logger.info("[RAG] Retrieved %d/%d chunks for query: '%s'",
                    len(filtered_chunks), len(raw_docs), query[:60])
        return context

    except Exception as e:
        # Graceful degradation — RAG failure must NOT crash the call
        logger.error("[RAG] retrieve_context() failed: %s", e, exc_info=True)
        return ""