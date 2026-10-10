let gexStrikesExpanded = false;

function toggleGexStrikes() {
    gexStrikesExpanded = !gexStrikesExpanded;
    const panel = $('gex-strike-panel');
    const arrow = $('gex-strike-arrow');
    const txt = $('gex-strike-toggle-text');
    if (!panel) return;
    if (gexStrikesExpanded) {
        panel.classList.remove('hidden');
        if (arrow) arrow.classList.add('rotate-180');
        if (txt) txt.innerText = '클릭하여 접기';
    } else {
        panel.classList.add('hidden');
        if (arrow) arrow.classList.remove('rotate-180');
        if (txt) txt.innerText = '클릭하여 펼치기';
    }
}

function renderSpreadOptimizer(opt) {
    const card = $('spread-optimizer-card');
    if (!card) return;
    if (!opt || !opt.available) {
        setText('opt-call-status', '대기');
        setText('opt-put-status', '대기');
        return;
    }
    const c = opt.call_spread;
    if (c) {
        setText('opt-call-strikes', `Short ${c.short} / Long ${c.long}`);
        setText('opt-call-credit', c.credit !== null ? `$${c.credit.toFixed(2)} (${(c.credit * 10).toFixed(1)}%)` : '화요일 09:30 ET 산출');
        setText('opt-call-bound', `${c.boundary}`);
        setText('opt-call-guide', c.guide || '--');
        const stEl = $('opt-call-status');
        if (stEl) {
            stEl.innerText = c.badge || '대기';
            stEl.className = `text-[9px] sm:text-xs font-mono font-bold px-1.5 py-0.5 rounded ${c.status === 'SWEET_SPOT' ? 'bg-emerald-950 text-emerald-300 border border-emerald-600' : (c.status === 'LOW_PREMIUM' ? 'bg-slate-800 text-slate-400 border border-slate-700' : (c.status === 'WAITING' ? 'bg-slate-800 text-indigo-300 border border-indigo-700' : 'bg-amber-950 text-amber-300 border border-amber-600'))}`;
        }
    }
    const p = opt.put_spread;
    if (p) {
        setText('opt-put-strikes', `Short ${p.short} / Long ${p.long}`);
        setText('opt-put-credit', p.credit !== null ? `$${p.credit.toFixed(2)} (${(p.credit * 10).toFixed(1)}%)` : '화요일 09:30 ET 산출');
        setText('opt-put-bound', `${p.boundary}`);
        setText('opt-put-guide', p.guide || '--');
        const stEl = $('opt-put-status');
        if (stEl) {
            stEl.innerText = p.badge || '대기';
            stEl.className = `text-[9px] sm:text-xs font-mono font-bold px-1.5 py-0.5 rounded ${p.status === 'SWEET_SPOT' ? 'bg-emerald-950 text-emerald-300 border border-emerald-600' : (p.status === 'LOW_PREMIUM' ? 'bg-slate-800 text-slate-400 border border-slate-700' : (p.status === 'WAITING' ? 'bg-slate-800 text-indigo-300 border border-indigo-700' : 'bg-amber-950 text-amber-300 border border-amber-600'))}`;
        }
    }
}

function renderGex(g) {
    const note = $('gex-note');
    if (!g || !g.available) {
        setText('gex-source', NA); setText('gex-meta', NA); setText('gex-em', NA);
        setText('gex-put-wall', NA); setText('gex-flip', NA); setText('gex-call-wall', NA);
        if (note) { note.classList.remove('hidden'); note.innerText = (g && g.reason) || 'GEX 데이터를 불러올 수 없습니다.'; }
        renderSpreadOptimizer(null);
        return;
    }
    if (note) note.classList.add('hidden');
    setText('gex-source', srcShort(g.source));
    const is0dte = g.is_0dte ? '0DTE 당일 만기' : '익일 만기';
    setText('gex-meta', `${g.expiration || ''} (${is0dte}) · 행사가 ${g.strike_count || 0}개`);
    setText('gex-em', g.expected_move || NA);
    setText('gex-put-wall', isNum(g.put_wall) ? fmt(g.put_wall, 1) : NA);
    setText('gex-flip', isNum(g.gamma_flip) ? fmt(g.gamma_flip, 1) : NA);
    setText('gex-call-wall', isNum(g.call_wall) ? fmt(g.call_wall, 1) : NA);

    const regime = $('gex-regime');
    if (regime && g.regime_text) {
        regime.classList.remove('hidden');
        regime.innerText = `Net GEX: ${g.net_gex || '--'} · ${g.regime_text}`;
    }

    // EM Bar & Marker
    const spot = isNum(g.gamma_flip) ? g.gamma_flip : null;
    const em = isNum(g.em_pt) ? g.em_pt : null;
    if (spot && em) {
        const minScale = spot - em * 2.2, maxScale = spot + em * 2.2;
        setText('scale-min', minScale.toFixed(0));
        setText('scale-max', maxScale.toFixed(0));
        setText('em-low-val', (spot - em).toFixed(1));
        setText('em-high-val', (spot + em).toFixed(1));
        const pct = (v) => Math.max(0, Math.min(100, ((v - minScale) / (maxScale - minScale)) * 100));
        
        const emBar = $('em-range-bar');
        if (emBar) {
            const left = pct(spot - em), right = pct(spot + em);
            emBar.style.left = `${left}%`;
            emBar.style.width = `${right - left}%`;
        }
        const curM = $('marker-current');
        if (curM) { curM.style.left = `${pct(spot)}%`; setText('marker-current-val', spot.toFixed(1)); }
        const pLine = $('marker-put-line'), cLine =$('marker-call-line');
        if (pLine && isNum(g.put_wall)) { pLine.style.display = 'block'; pLine.style.left = `${pct(g.put_wall)}%`; }
        if (cLine && isNum(g.call_wall)) { cLine.style.display = 'block'; cLine.style.left = `${pct(g.call_wall)}%`; }
    }

    // Strike Rows
    const tbody = $('gex-strike-rows');
    const toggle = $('gex-strike-toggle');
    if (g.by_strike && g.by_strike.length) {
        if (toggle) toggle.classList.remove('hidden');
        if (tbody) {
            tbody.innerHTML = g.by_strike.map(s => `
                <tr class="border-b border-slate-800/60 hover:bg-slate-900/50">
                    <td class="py-1 pr-2 font-bold text-white">${s.strike}</td>
                    <td class="py-1 pr-2 text-right text-emerald-400">${s.call_oi.toLocaleString()}</td>
                    <td class="py-1 pr-2 text-right text-rose-400">${s.put_oi.toLocaleString()}</td>
                    <td class="py-1 pr-2 text-right text-emerald-300 font-bold">${s.call_vol.toLocaleString()}</td>
                    <td class="py-1 pr-2 text-right text-rose-300 font-bold">${s.put_vol.toLocaleString()}</td>
                    <td class="py-1 pr-2 text-right font-bold ${s.net_gex_m >= 0 ? 'text-emerald-400' : 'text-rose-400'}">${s.net_gex_m > 0 ? '+' : ''}${s.net_gex_m}</td>
                </tr>
            `).join('');
        }
    }

    // 0DTE Credit Spread Optimizer 렌더링 호출
    renderSpreadOptimizer(g.spread_optimizer);
}
