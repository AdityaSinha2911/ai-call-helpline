/*
   Handles: Navigation, Voice STT, TTS, API calls, History
   Backend: FastAPI at localhost:8000
*/

const API_BASE = "http://localhost:8000";

// State 
let sessionId       = generateSessionId();
let chatHistory     = [];   // {role, content}
let conversationLog = [];   // full log for history page
let isListening     = false;
let isSpeaking      = false;
let recognition     = null;
let currentUtterance = null;

// DOM refs 
const chatWindow      = document.getElementById("chatWindow");
const textInput       = document.getElementById("textInput");
const sendBtn         = document.getElementById("sendBtn");
const micBtn          = document.getElementById("micBtn");
const micStatus       = document.getElementById("micStatus");
const charCount       = document.getElementById("charCount");
const statusDot       = document.getElementById("statusDot");
const statusText      = document.getElementById("statusText");
const sessionDisplay  = document.getElementById("sessionIdDisplay");
const newSessionBtn   = document.getElementById("newSessionBtn");
const clearChatBtn    = document.getElementById("clearChatBtn");
const exportBtn       = document.getElementById("exportBtn");
const historyList     = document.getElementById("historyList");

// Init 
document.addEventListener("DOMContentLoaded", () => {
  updateSessionDisplay();
  checkBackendStatus();
  setInterval(checkBackendStatus, 30000);
  setupNavigation();
  setupSpeechRecognition();
  setupInputHandlers();
  setupButtons();
});


//  NAVIGATION
function setupNavigation() {
  document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", e => {
      e.preventDefault();
      const page = item.dataset.page;
      switchPage(page);
      document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
      item.classList.add("active");
    });
  });
}

function switchPage(name) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.getElementById(`page-${name}`).classList.add("active");
  if (name === "history") renderHistory();
}


//  SESSION
function generateSessionId() {
  return "sess-" + Math.random().toString(36).slice(2, 10).toUpperCase();
}
function updateSessionDisplay() {
  sessionDisplay.textContent = sessionId;
}
newSessionBtn.addEventListener("click", () => {
  sessionId   = generateSessionId();
  chatHistory = [];
  updateSessionDisplay();
  clearChat();
  showToast("New session started");
});


//  BACKEND STATUS CHECK
async function checkBackendStatus() {
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(5000) });
    if (res.ok) {
      statusDot.className = "status-dot online";
      statusText.textContent = "Online";
    } else {
      throw new Error("not ok");
    }
  } catch {
    statusDot.className = "status-dot offline";
    statusText.textContent = "Offline";
  }
}

//  SPEECH RECOGNITION (STT)
function setupSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    micBtn.title = "Speech recognition not supported in this browser";
    micBtn.style.opacity = "0.4";
    micBtn.style.cursor  = "not-allowed";
    micStatus.textContent = "⚠ Speech not supported — use Chrome";
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang        = "en-IN";
  recognition.interimResults = true;
  recognition.continuous  = false;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    isListening = true;
    micBtn.classList.add("listening");
    micStatus.textContent = "🔴 Listening... speak now";
    micStatus.classList.add("active");
  };

  recognition.onresult = (e) => {
    const transcript = Array.from(e.results)
      .map(r => r[0].transcript)
      .join("");
    textInput.value = transcript;
    updateCharCount();

    // Auto-resize textarea
    textInput.style.height = "auto";
    textInput.style.height = textInput.scrollHeight + "px";
  };

  recognition.onend = () => {
    isListening = false;
    micBtn.classList.remove("listening");
    micStatus.textContent = "🎤 Click mic to speak";
    micStatus.classList.remove("active");

    // Auto-send if we got something
    if (textInput.value.trim()) {
      setTimeout(() => handleSend(), 400);
    }
  };

  recognition.onerror = (e) => {
    isListening = false;
    micBtn.classList.remove("listening");
    micStatus.classList.remove("active");
    if (e.error === "not-allowed") {
      micStatus.textContent = "⚠ Microphone access denied";
      showToast("Please allow microphone access", true);
    } else {
      micStatus.textContent = "🎤 Click mic to speak";
    }
  };
}

micBtn.addEventListener("click", () => {
  if (!recognition) return;
  if (isListening) {
    recognition.stop();
  } else {
    // Stop any speaking first
    if (isSpeaking) stopSpeaking();
    try {
      recognition.start();
    } catch(e) {
      // Already started
    }
  }
});


//  TEXT-TO-SPEECH (TTS)
function speak(text) {
  if (!window.speechSynthesis) return;
  stopSpeaking();

  // Strip emojis and clean up for speaking
  const clean = text.replace(/[\u{1F600}-\u{1F6FF}]/gu, "").trim();
  currentUtterance = new SpeechSynthesisUtterance(clean);
  currentUtterance.lang  = "en-IN";
  currentUtterance.rate  = 0.95;
  currentUtterance.pitch = 1;

  // Pick a nice voice if available
  const voices = window.speechSynthesis.getVoices();
  const preferred = voices.find(v =>
    v.lang.startsWith("en") && (v.name.includes("Google") || v.name.includes("Female"))
  );
  if (preferred) currentUtterance.voice = preferred;

  currentUtterance.onstart = () => { isSpeaking = true; };
  currentUtterance.onend   = () => { isSpeaking = false; };

  window.speechSynthesis.speak(currentUtterance);
}

function stopSpeaking() {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  isSpeaking = false;
}

//  INPUT HANDLERS
function setupInputHandlers() {
  textInput.addEventListener("input", () => {
    updateCharCount();
    textInput.style.height = "auto";
    textInput.style.height = Math.min(textInput.scrollHeight, 120) + "px";
  });

  textInput.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });
}

function updateCharCount() {
  charCount.textContent = `${textInput.value.length} / 500`;
}

//  BUTTONS
function setupButtons() {
  sendBtn.addEventListener("click", handleSend);

  clearChatBtn.addEventListener("click", () => {
    clearChat();
    showToast("Chat cleared");
  });

  exportBtn.addEventListener("click", exportLog);
}

//  SEND MESSAGE
async function handleSend() {
  const text = textInput.value.trim();
  if (!text) return;

  // Clear input
  textInput.value = "";
  textInput.style.height = "auto";
  updateCharCount();
  sendBtn.disabled = true;

  // Hide welcome screen
  const welcome = document.getElementById("welcomeScreen");
  if (welcome) welcome.remove();

  // Append user message
  appendMessage("user", text);
  logMessage("user", text);

  // Add to chat history for memory
  chatHistory.push({ role: "user", content: text });

  // Show typing
  const typingEl = showTyping();

  try {
    const response = await callBackend(text);
    typingEl.remove();

    const reply = response.answer || response.message || "Sorry, I didn't get a response.";
    const blocked = response.blocked || false;

    appendMessage("ai", reply, blocked);
    logMessage("ai", reply);
    chatHistory.push({ role: "assistant", content: reply });

    // Keep last 8 messages in memory
    if (chatHistory.length > 8) chatHistory = chatHistory.slice(-8);

    // Speak response
    if (!blocked) speak(reply);

  } catch (err) {
    typingEl.remove();
    const errMsg = "⚠ Could not reach the backend. Make sure FastAPI is running on port 8000.";
    appendMessage("ai", errMsg, false, true);
    showToast("Backend unreachable", true);
  }

  sendBtn.disabled = false;
  textInput.focus();
}


//  API CALL
async function callBackend(query) {
  const regMatch = query.match(/\b(\d{4}[A-Z]{2}\d{3}|\d{4,10})\b/i);

  const payload = {
    query:               query,
    session_id:          sessionId,
    chat_history:        chatHistory.slice(-6),
    registration_number: regMatch ? regMatch[1].toUpperCase() : null
  };

  const res = await fetch(`${API_BASE}/query`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(payload),
    signal:  AbortSignal.timeout(30000)
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }

  return await res.json();
}

//  CHAT UI
function appendMessage(role, text, blocked = false, isError = false) {
  const wrap = document.createElement("div");
  wrap.className = `chat-message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.textContent = role === "user" ? "You" : "AI";

  const body = document.createElement("div");
  body.className = "msg-body";

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble" + (blocked ? " blocked" : "");

  if (blocked) {
    const badge = document.createElement("div");
    badge.className = "blocked-badge";
    badge.textContent = "Blocked";
    bubble.appendChild(badge);
  }

  const content = document.createElement("div");
  content.textContent = text;
  bubble.appendChild(content);

  const time = document.createElement("div");
  time.className = "msg-time";
  time.textContent = formatTime(new Date());

  body.appendChild(bubble);
  body.appendChild(time);
  wrap.appendChild(avatar);
  wrap.appendChild(body);
  chatWindow.appendChild(wrap);
  scrollToBottom();
}

function showTyping() {
  const wrap = document.createElement("div");
  wrap.className = "chat-message ai";

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.textContent = "AI";

  const indicator = document.createElement("div");
  indicator.className = "typing-indicator";
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement("span");
    dot.className = "typing-dot";
    indicator.appendChild(dot);
  }

  wrap.appendChild(avatar);
  wrap.appendChild(indicator);
  chatWindow.appendChild(wrap);
  scrollToBottom();
  return wrap;
}

function scrollToBottom() {
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function clearChat() {
  chatWindow.innerHTML = `
    <div class="chat-welcome" id="welcomeScreen">
      <div class="welcome-icon">
        <svg viewBox="0 0 56 56" fill="none">
          <circle cx="28" cy="28" r="27" stroke="currentColor" stroke-width="1.2" opacity="0.3"/>
          <circle cx="28" cy="28" r="18" stroke="currentColor" stroke-width="1" opacity="0.2"/>
          <path d="M16 28 Q28 16 40 28 Q28 40 16 28Z" fill="currentColor" opacity="0.15"/>
          <circle cx="28" cy="28" r="7" fill="currentColor" opacity="0.5"/>
        </svg>
      </div>
      <h2>Hello, I'm your College AI</h2>
      <p>Ask me anything about fees, attendance, exams, hostel, scholarships, or documents.</p>
      <div class="suggestion-chips">
        <button class="chip" onclick="fillSuggestion('What is my fee status?')">💰 Fee Status</button>
        <button class="chip" onclick="fillSuggestion('Show my attendance percentage')">📊 Attendance</button>
        <button class="chip" onclick="fillSuggestion('When are the upcoming exams?')">📝 Exams</button>
        <button class="chip" onclick="fillSuggestion('How to apply for hostel?')">🏠 Hostel</button>
        <button class="chip" onclick="fillSuggestion('Tell me about scholarship eligibility')">🎓 Scholarship</button>
        <button class="chip" onclick="fillSuggestion('I want to raise a complaint')">🎫 Complaint</button>
      </div>
    </div>`;
  chatHistory = [];
}


//  SUGGESTION CHIPS
function fillSuggestion(text) {
  textInput.value = text;
  updateCharCount();
  textInput.focus();
  textInput.style.height = "auto";
  textInput.style.height = textInput.scrollHeight + "px";
}

//  HISTORY
function logMessage(role, text) {
  conversationLog.push({ role, text, time: new Date() });
}

function renderHistory() {
  if (conversationLog.length === 0) {
    historyList.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 64 64" fill="none" width="52" height="52">
          <circle cx="32" cy="32" r="30" stroke="currentColor" stroke-width="1.5" opacity="0.25"/>
          <path d="M22 32h20M32 22v20" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.3"/>
        </svg>
        <p>No history yet.<br>Start a conversation first.</p>
      </div>`;
    return;
  }

  historyList.innerHTML = "";
  conversationLog.forEach(entry => {
    const item = document.createElement("div");
    item.className = "history-item";
    item.innerHTML = `
      <div class="history-item-header">
        <span class="history-role ${entry.role}">${entry.role === "user" ? "You" : "AI Assistant"}</span>
        <span class="history-time">${formatTime(entry.time)}</span>
      </div>
      <div class="history-text">${escapeHtml(entry.text)}</div>`;
    historyList.appendChild(item);
  });
}

function exportLog() {
  if (conversationLog.length === 0) {
    showToast("No history to export", true);
    return;
  }
  const lines = conversationLog.map(e =>
    `[${formatTime(e.time)}] ${e.role.toUpperCase()}: ${e.text}`
  ).join("\n");

  const blob = new Blob([`AI Helpline — Session ${sessionId}\n${"─".repeat(50)}\n\n${lines}`], { type: "text/plain" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = `helpline-log-${sessionId}.txt`;
  a.click();
  URL.revokeObjectURL(url);
  showToast("Log exported");
}


//  UTILITIES
function formatTime(date) {
  return date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

function escapeHtml(str) {
  return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function showToast(message, isError = false) {
  const existing = document.querySelector(".toast");
  if (existing) existing.remove();

  const toast = document.createElement("div");
  toast.className = "toast" + (isError ? " error" : "");
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}
