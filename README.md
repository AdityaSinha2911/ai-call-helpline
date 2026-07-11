
# AI Voice-Based College Helpline System 📞🤖

An automated, voice-based AI support platform that handles real-time college queries (fees, exams, attendance, tickets) over regular phone calls without human intervention.

The system uses a fine-tuned local LLM for natural speech generation, combined with deterministic Python code for strict logical control and database interaction.

---

## 🏗️ Core Architectural Principle

> 💡 **The Golden Rule:** Code controls all logic. The LLM is strictly the language layer.
> 
> 

In this system, the AI never decides if a student is authorized, never makes database updates directly, and never runs critical business logic.

* **Deterministic Code:** Handles intent detection, OTP verification, database fetches, guard enforcement, and ticket creation.


* **LLM Layer:** Only takes raw data prepared by the code and converts it into natural, conversational language.



This completely eliminates hallucinations and prevents prompt-injection security vulnerabilities in production.

---

## 🛠️ System Architecture & Call Flow

The end-to-end call lifecycle follows this exact sequential process:

```
[Student Call] ──> [Twilio Voice API (STT)] ──> [FastAPI Backend]
                                                       │
                                            ┌──────────┴──────────┐
                                            ▼                     ▼
                                    [Security Guards]     [STT Correction Engine]
                                            │                     │
                                            ▼                     ▼
                                    [Intent Handler] ──> [Path Router]
                                                                  │
                           ┌──────────────────────┬───────────────┴──────────────┐
                           ▼                      ▼                              ▼
                  (Personal Query)        (General Query)               (Issue / Complaint)
                  [SQLite Data Fetch]    [ChromaDB RAG Engine]         [Auto-Ticket Creation]
                           │                      │                              │
                           └──────────────────────┼──────────────────────────────┘
                                                  ▼
                                      [Prompt Assembly Layer]
                                                  │
                                                  ▼
                                       [Local Llama 3.1 Model]
                                                  │
                                                  ▼
                                      [Output Safety Guard]
                                                  │
                                                  ▼
                                         [Twilio Audio (TTS)]

```

1. **Voice Input:** A student calls the helpline number. **Twilio** captures the stream and transcribes speech into text using Speech-to-Text (STT).


2. **Ingress & Security:** The transcription hitting our **FastAPI** backend is instantly scanned by a 3-layer security system (`input_guard.py`, `topic_guard.py`) to block jailbreaks and off-topic requests.


3. **Phonetic Correction:** The text passes through `stt_handler.py` to fix common telephony mishears (e.g., mishearing "fees" as "peace") and extract structured 8-digit registration IDs.


4. **Smart Path Routing:**
* **Personal Path:** Bypasses LLM retrieval, reading directly from an SQLite database containing 500 fake student profiles.


* **General Path:** The **RAG engine** queries vector data in **ChromaDB** using `all-MiniLM-L6-v2` embeddings to gather public college info.


* **Problem Path:** Automatically logs a complaint into a custom support ticket system.




5. **Inference & Egress:** Data is assembled into a strict context template, passed to a locally deployed **Llama 3.1 model** running on **Ollama**, validated by `output_guard.py`, and converted back to spoken voice using Text-to-Speech (TTS).



---

## 📂 Repository Structure

```
AI-HELPLINE/
│
├── backend/                      # Main server engine
│   ├── main.py                   # FastAPI entrypoint and endpoint routes
│   ├── database.py               # SQLite ORM & query logic layer
│   ├── college.db                # Mock database containing 500 student records
│   └── guards/                   # 3-Layer security ecosystem
│       ├── input_guard.py        # Validates incoming queries against jailbreaks
│       ├── topic_guard.py        # Keeps conversations strictly within university topics
│       └── output_guard.py       # Validates AI answers before streaming out
│
├── twilio_voice/                 # Telephony orchestrator
│   ├── call_handler.py           # Controls streaming speech state machine
│   ├── stt_handler.py            # Regex filters & phonetic mishear corrections
│   ├── tts_handler.py            # Audio streaming output conversion
│   ├── session_store.py          # Temporary in-memory call context retention
│   └── otp_helper.py             # Security verification module
│
├── rag/                          # Retrieval-Augmented Generation library
│   └── ...                       # ChromaDB integration and text embeddings
│
├── data/                         # Knowledge Base text documents for RAG vectors
│
├── frontend/                     # Administration Monitoring Panel
│   ├── index.html                # Live call analytics view
│   ├── ticket-list.html          # Open student support complaints dashboard
│   └── app.js                    # UI state interaction scripts
│
├── training/                     # Model compilation & fine-tuning workflows
│   ├── downloading_model.py      # Base weight download automation
│   ├── model_training_example.py # Low-Rank Adaptation (LoRA) fine-tuning notebook code
│   └── convert_to_gguf_example.py# Formats model into GGUF architecture
│
├── college.gguf                  # Quantized fine-tuned model checkpoint
├── Modelfile                     # System instructions configuration for Ollama
└── make_call.py                  # Outbound automated call testing utility

```

---

## 🚀 Model Fine-Tuning Details

Instead of using expensive public APIs, this system runs completely locally on consumer-grade hardware.

* **Base Model:** Llama 3.1.


* **Training Method:** **LoRA (Low-Rank Adaptation)** executed on Google Colab free-tier. Rather than modifying billions of global parameters, small adapter weights were trained, drastically cutting memory footprints.


* **Format:** Converted and quantized into **GGUF format** to enable high-efficiency execution locally inside **Ollama**.



---

## 📈 Current Project Milestone Tracker

| Feature Layer | System Component | Status |
| --- | --- | --- |
| **Model** | LoRA Fine-Tuning & GGUF Pipeline

 | Complete |
| **Security** | 3-Layer Input/Topic/Output Guards

 | Complete |
| **Data Engine** | 500 Student Mock Profiles Generator

 | Complete |
| **Telephony** | Twilio Live Voice Connection Flow

 | Complete |
| **Signal Processing** | Phonetic Mishear Fix & ID Extraction

 | Complete |
| **Knowledge RAG** | ChromaDB Context Injection Layer

 | Complete |
| **Analytics Dashboard** | Live Call Monitor & Ticket UI Panels

 | Complete |
| **Testing** | 110-Test Case Verification Suite (`test.py`)

 | Complete |
| **Identity Locking** | Live Call OTP Verification Integration

 | ⏳ Up Next |

---

## 📄 License

This project is licensed under the **Creative Commons Attribution-NonCommercial 4.0 International License**. Commercial utilization of this source code or derived model weights is restricted without prior written consent.

© 2026 Aditya Sinha. All rights reserved.
