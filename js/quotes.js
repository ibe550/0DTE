function renderQuote(pfx, q, opts = {}) {
    if (!q) {
        setText(pfx + '-price', NA); setText(pfx + '-change', NA); setText(pfx + '-source', NA);
        setTone(pfx + '-price', 'text-slate-500'); setTone(pfx + '-change', 'text-slate-500');
        return;
    }
    setText(pfx + '-price', fmt(q.price, 2));
    const dir = opts.invert ? -q.change : q.change;
    const chg = isNum(q.change) ? `${sgn(q.change)}${opts.pct && isNum(q.change_pct) ? ` (${sgn(q.change_pct)}%)` : ''}` : NA;
    setText(pfx + '-change', chg);
    setTone(pfx + '-price', toneOf(dir));
    setTone(pfx + '-change', toneOf(dir));
    const s = $(pfx + '-source');
    if (s) { s.innerText = srcShort(q.source); s.title = q.source || ''; }
}

function renderYields(y) {
    const pairs = [
        ['yield-3m', 'y3m', 'yield-3m-src', 'yield-3m-chg', 'y3m_change_text', 'y3m_change_bp'],
        ['yield-10y', 'y10', 'yield-10y-src', 'yield-10y-chg', 'y10_change_text', 'y10_change_bp'],
        ['yield-30y', 'y30', 'yield-30y-src', 'yield-30y-chg', 'y30_change_text', 'y30_change_bp'],
    ];
    pairs.forEach(([id, key, srcId, chgId, chgTextKey, chgBpKey]) => {
        setText(id, y ? y[key] : null);
        setTone(id, y && y[key] ? 'text-slate-200' : 'text-slate-500');
        const s = y && y.sources ? y.sources[key] : null;
        setText(srcId, srcShort(s));
        const bp = y ? y[chgBpKey] : null;
        setText(chgId, y ? y[chgTextKey] : null);
        
        // 금리 상승(bp > 0)시 빨간색, 하락(bp < 0)시 녹색 적용
        setTone(chgId, !isNum(bp) ? 'text-slate-500' : (bp > 0 ? 'text-rose-400' : (bp < 0 ? 'text-emerald-400' : 'text-slate-400')));
    });
    setText('yield-spread', y ? y.spread : null);
    const bp = y && y.spread ? parseInt(y.spread, 10) : NaN;
    setTone('yield-spread', isNaN(bp) ? 'text-slate-500' : (bp < 0 ? 'text-rose-400' : 'text-emerald-400'));
}

function renderPolymarket(p) {
    if (!p || !p.available) {
        setText('poly-title', 'SPX 마켓 집계 대기 중...');
        setText('poly-summary', '--');
        return;
    }
    setText('poly-title', p.title);
    setText('poly-summary', p.summary);
    const srcEl = $('poly-source');
    if (srcEl && p.source) srcEl.innerText = p.source;
}

function renderRsi(r) {
    const badge = $('header-rsi-badge');
    if (!badge || !r || !isNum(r.val)) {
        if (badge) badge.classList.add('hidden');
        return;
    }
    badge.classList.remove('hidden');
    const val = r.val.toFixed(1);
    let statusText = '중립', colorCls = 'bg-slate-800 text-slate-300 border-slate-700';
    if (r.val >= 70) { statusText = '과매수'; colorCls = 'bg-rose-950/90 text-rose-300 border-rose-800/80 animate-pulse'; }
    else if (r.val <= 30) { statusText = '과매도'; colorCls = 'bg-emerald-950/90 text-emerald-300 border-emerald-800/80 animate-pulse'; }
    else if (r.val >= 55) { statusText = '상승'; colorCls = 'bg-amber-950/70 text-amber-300 border-amber-800/60'; }
    else if (r.val <= 45) { statusText = '하락'; colorCls = 'bg-indigo-950/70 text-indigo-300 border-indigo-800/60'; }
    badge.className = `font-mono px-1.5 py-0.5 rounded font-bold border ${colorCls} text-[9px] lg:text-xs`;
    badge.innerText = `RSI ${val} (${statusText})`;
}

function renderShockAlert(alert) {
    const banner = $('shock-alert-banner');
    if (!banner || !alert || !alert.active) {
        if (banner) banner.classList.add('hidden');
        return;
    }
    banner.classList.remove('hidden');
    setText('shock-alert-title', alert.title || '⚡ [변동성 쇼크]');
    setText('shock-alert-time', alert.timestamp || '');
    const isSurge = alert.type === 'SURGE', isDrop = alert.type === 'DROP';
    banner.className = `card mb-2 lg:mb-3 p-2.5 lg:p-3.5 border-2 shadow-lg transition-all duration-300 ${isSurge ? 'border-emerald-500 bg-emerald-950/90' : (isDrop ? 'border-rose-500 bg-rose-950/90' : 'border-purple-500 bg-purple-950/90')}`;
    $('shock-alert-dot').className = `w-2.5 h-2.5 lg:w-3 lg:h-3 rounded-full animate-ping inline-block mr-1 ${isSurge ? 'bg-emerald-400' : (isDrop ? 'bg-rose-500' : 'bg-purple-400')}`;
    if (alert.elapsed_text) {
        $('shock-alert-elapsed').className = `text-[9px] sm:text-xs lg:text-sm font-mono font-bold px-1.5 lg:px-2 py-0.5 rounded ${isSurge ? 'bg-emerald-900/80 text-emerald-200' : (isDrop ? 'bg-rose-900/80 text-rose-200' : 'bg-purple-900/80 text-purple-200')}`;
        setText('shock-alert-elapsed', alert.elapsed_text);
    }
    $('shock-alert-reasons').innerHTML = (alert.details || []).map(d => `<div class="flex items-center space-x-1.5"><span class="w-1.5 h-1.5 lg:w-2 lg:h-2 rounded-full ${isSurge ? 'bg-emerald-400' : (isDrop ? 'bg-rose-400' : 'bg-purple-400')} inline-block"></span><span class="font-bold">${d}</span></div>`).join('');
}

function renderStatus(data) {
    $('global-source-badge').innerText = `Source: ${data.source_summary}`;
    const line = $('schwab-status-line');
    const okSchwab = (data.schwab_status || '').startsWith('연결됨') && !(data.schwab_status || '').includes('Yahoo 로 대체');
    if (okSchwab) line.classList.add('hidden');
    else {
        line.classList.remove('hidden');
        line.innerText = `⚠ ${data.schwab_status}${/Yahoo [1-9]/.test(data.source_summary || '') ? ' → Yahoo 로 자동 대체 중' : ''}`;
    }
}
