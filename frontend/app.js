// Configure this before loading the dashboard when the API is hosted separately:
// window.HELPLINE_API_BASE = "https://your-api.example.com";
const API = (window.HELPLINE_API_BASE || "http://127.0.0.1:8000").replace(/\/$/, "");

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || `Request failed (${response.status})`);
  }
  return payload;
}

async function fetchTickets(status = null) {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiRequest(`/admin/tickets${query}`);
}

async function fetchTicketStats() {
  return apiRequest("/admin/ticket-stats");
}

async function closeTicket(ticketId, adminNote = "") {
  return apiRequest("/admin/close-ticket", {
    method: "POST",
    body: JSON.stringify({ ticket_id: ticketId, admin_note: adminNote })
  });
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

function timeAgo(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

function statusBadge(status) {
  const safe = escapeHtml(status || "Unknown");
  const classes = { "Open": "badge-open", "Closed": "badge-closed", "In Progress": "badge-progress" };
  return `<span class="badge ${classes[status] || "badge-unknown"}">${safe}</span>`;
}

function categoryEmoji(category) {
  return ({ fees: "💰", hostel: "🏠", exam: "📝", document: "📄",
    technical: "🔧", attendance: "📊", other: "❓" })[category] || "❓";
}

function truncate(value, limit = 60) {
  const text = String(value ?? "");
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function showToast(message, type = "success") {
  let toast = document.getElementById("dashboardToast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "dashboardToast";
    toast.className = "dashboard-toast";
    toast.setAttribute("role", "status");
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.dataset.type = type;
  toast.classList.add("visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("visible"), 3200);
}

function setActiveNav() {
  const page = window.location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".nav-item").forEach(link => {
    const active = link.dataset.page === page;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

document.addEventListener("DOMContentLoaded", setActiveNav);
