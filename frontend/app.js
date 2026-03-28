const API = 'http://127.0.0.1:8000';

// ── API FUNCTIONS ──

async function fetchTickets(status = null) {
  try {
    const url = status
      ? `${API}/admin/tickets?status=${status}`
      : `${API}/admin/tickets`;
    const res = await fetch(url);
    return await res.json();
  } catch (e) {
    console.error('[API] fetchTickets failed:', e);
    return [];
  }
}

async function fetchTicketStats() {
  try {
    const res = await fetch(`${API}/admin/ticket-stats`);
    return await res.json();
  } catch (e) {
    console.error('[API] fetchTicketStats failed:', e);
    return { total: 0, open: 0, closed: 0, in_progress: 0, by_category: {} };
  }
}

async function closeTicket(ticketId, adminNote = '') {
  try {
    const res = await fetch(`${API}/admin/close-ticket`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticket_id: ticketId, admin_note: adminNote })
    });
    return await res.json();
  } catch (e) {
    console.error('[API] closeTicket failed:', e);
    return { success: false };
  }
}

async function fetchDashboardStats() {
  try {
    const res = await fetch(`${API}/admin/ticket-stats`);
    return await res.json();
  } catch (e) {
    console.error('[API] fetchDashboardStats failed:', e);
    return {};
  }
}

// ── UTILITY FUNCTIONS ──

function formatDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatTime(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

function timeAgo(dateStr) {
  if (!dateStr) return '—';
  const now = new Date();
  const d = new Date(dateStr);
  const diff = Math.floor((now - d) / 1000);
  if (diff < 60)    return `${diff}s ago`;
  if (diff < 3600)  return `${Math.floor(diff/60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
  return `${Math.floor(diff/86400)}d ago`;
}

function statusBadge(status) {
  const map = {
    'Open':        'badge-open',
    'Closed':      'badge-closed',
    'In Progress': 'badge-progress',
  };
  const cls = map[status] || 'badge-open';
  return `<span class="badge ${cls}">${status}</span>`;
}

function categoryEmoji(cat) {
  const map = {
    fees: '💰', hostel: '🏠', exam: '📝',
    document: '📄', technical: '🔧', attendance: '📊', other: '❓'
  };
  return map[cat] || '❓';
}

function truncate(str, n = 60) {
  if (!str) return '—';
  return str.length > n ? str.slice(0, n) + '…' : str;
}

// ── ACTIVE NAV ──
function setActiveNav() {
  const page = window.location.pathname.split('/').pop();
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.remove('active');
    if (el.dataset.page === page) el.classList.add('active');
  });
}

document.addEventListener('DOMContentLoaded', setActiveNav);
