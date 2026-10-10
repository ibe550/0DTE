const NA = 'N/A';
const $ = (id) => document.getElementById(id);
const TONES = ['text-emerald-400', 'text-rose-400', 'text-slate-300', 'text-slate-200', 'text-slate-500', 'text-amber-400'];
const isNum = (v) => typeof v === 'number' && isFinite(v);

function setText(id, v, fallback = NA) {
    const el = $(id);
    if (el) el.innerText = (v === null || v === undefined || v === '') ? fallback : v;
}

function setTone(id, cls) {
    const el = $(id);
    if (!el) return;
    el.classList.remove(...TONES);
    el.classList.add(cls);
}

const toneOf = (v) => (!isNum(v) ? 'text-slate-500' : (v > 0 ? 'text-emerald-400' : (v < 0 ? 'text-rose-400' : 'text-slate-300')));
const toneByName = (t) => (t === 'bull' ? 'text-emerald-400' : (t === 'bear' ? 'text-rose-400' : 'text-slate-300'));
const fmt = (v, d = 2) => (isNum(v) ? v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }) : NA);
const sgn = (v, d = 2) => (isNum(v) ? `${v > 0 ? '+' : ''}${v.toFixed(d)}` : NA);
const srcShort = (s) => (!s ? NA : s.replace('Charles Schwab', 'Schwab').replace('Yahoo Finance', 'Yahoo'));

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function updateClock() {
    const now = new Date();
    $('current-clock').innerText = now.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour12: false }) + ' ET';
}
setInterval(updateClock, 1000);
updateClock();
