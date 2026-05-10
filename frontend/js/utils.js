// ── API Base ────────────────────────────────────────────────────────────────
const API = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? ''       // same origin in dev
  : '';      // same origin in prod (FastAPI serves frontend)

async function apiFetch(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

// ── Session State ────────────────────────────────────────────────────────────
const State = {
  get(key) {
    try { return JSON.parse(sessionStorage.getItem('mm_' + key)); } catch { return null; }
  },
  set(key, val) {
    sessionStorage.setItem('mm_' + key, JSON.stringify(val));
  },
  clear(key) {
    sessionStorage.removeItem('mm_' + key);
  },
};

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  let container = document.getElementById('toasts');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toasts';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── Nav active state ─────────────────────────────────────────────────────────
function setActiveNav() {
  const page = window.location.pathname.split('/').pop().replace('.html', '') || 'index';
  document.querySelectorAll('.nav-links a').forEach(a => {
    const href = a.getAttribute('href').replace('.html', '').replace('/', '') || 'index';
    if (href === page || (page === '' && href === 'index')) {
      a.classList.add('active');
    }
  });
}

document.addEventListener('DOMContentLoaded', setActiveNav);

// ── Score ring helper ─────────────────────────────────────────────────────────
function renderScoreRing(container, score, max = 10, color = '#f5a623') {
  const pct = score / max;
  const r = 33;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - pct);
  container.innerHTML = `
    <div class="score-ring">
      <svg width="80" height="80" viewBox="0 0 80 80">
        <circle class="ring-bg" cx="40" cy="40" r="${r}"/>
        <circle class="ring-fill" cx="40" cy="40" r="${r}"
          stroke="${color}"
          stroke-dasharray="${circ}"
          stroke-dashoffset="${circ}"
          style="transition: stroke-dashoffset 1s ease"
        />
      </svg>
      <div class="score-text" style="color: ${color}">${score}</div>
    </div>`;
  // Animate after paint
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      const fill = container.querySelector('.ring-fill');
      if (fill) fill.style.strokeDashoffset = offset;
    });
  });
}

// ── Escape HTML ───────────────────────────────────────────────────────────────
function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}