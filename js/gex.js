function toggleGexStrikes() {
    const panel = $('gex-strike-panel'), arrow = $('gex-strike-arrow'), txt =$('gex-strike-toggle-text');
    if (panel.classList.contains('hidden')) {
        panel.classList.remove('hidden');
        arrow.style.transform = 'rotate(180deg)';
        txt.innerText = '클릭하여 접기';
    } else {
        panel.classList.add('hidden');
        arrow.style.transform = 'rotate(0deg)';
        txt.innerText = '클릭하여 펼치기';
    }
}

function renderGex(g, spx) {
    const ok = g && g.available, note = $('gex-note'), regime =$('gex-regime');
    setText('gex-source', g ? g.source : NA);
    ['marker-put-line', 'marker-flip-line', 'marker-call-line'].forEach(id => { $(id).style.display = 'none'; });$('em-range-bar').style.width = '0%';

    if (!ok) {
        note.classList.remove('hidden'); note.innerText = (g && g.reason) ? g.reason : 'GEX 데이터 없음';
        regime.classList.add('hidden'); setText('gex-meta', '');
        ['gex-em', 'gex-put-wall', 'gex-flip', 'gex-call-wall', 'em-low-val', 'em-high-val', 'scale-min', 'scale-max'].forEach(id => setText(id, NA));
        setText('marker-current-val', isNum(spx) ? spx.toFixed(1) : NA);
        $('gex-strike-toggle').classList.add('hidden');$('gex-strike-panel').classList.add('hidden');
        return;
    }

    if (!g.is_0dte) { note.classList.remove('hidden'); note.innerText = `0DTE 만기가 아니라 ${g.expiration} 만기 기준입니다`; }
    else { note.classList.add('hidden'); }

    setText('gex-meta', `만기 ${g.expiration}${g.is_0dte ? ' (0DTE)' : ''} · 순 GEX ${g.net_gex} · ${g.strike_count}개 행사가`);
    setText('gex-em', g.expected_move);
    setText('gex-put-wall', isNum(g.put_wall) ? g.put_wall : NA);
    setText('gex-flip', isNum(g.gamma_flip) ? g.gamma_flip : NA);
    setText('gex-call-wall', isNum(g.call_wall) ? g.call_wall : NA);
    regime.classList.remove('hidden'); regime.innerText = g.regime_text || '';

    const strikeToggle = $('gex-strike-toggle');
    if (g.by_strike && g.by_strike.length) {
        strikeToggle.classList.remove('hidden');
        $('gex-strike-rows').innerHTML = g.by_strike.map(r => {
            const netCls = r.net_gex_m > 0 ? 'text-emerald-400' : (r.net_gex_m < 0 ? 'text-rose-400' : 'text-slate-400');
            return `<tr class="border-t border-slate-800/60 hover:bg-slate-900/50 transition-colors">
                <td class="py-0.5 md:py-1.5 lg:py-2 pr-2 text-slate-200 font-bold">${r.strike}</td>
                <td class="py-0.5 md:py-1.5 lg:py-2 pr-2 text-right text-slate-300">${r.call_oi.toLocaleString()}</td>
                <td class="py-0.5 md:py-1.5 lg:py-2 pr-2 text-right text-slate-300">${r.put_oi.toLocaleString()}</td>
                <td class="py-0.5 md:py-1.5 lg:py-2 pr-2 text-right text-slate-400">${r.call_vol.toLocaleString()}</td>
                <td class="py-0.5 md:py-1.5 lg:py-2 pr-2 text-right text-slate-400">${r.put_vol.toLocaleString()}</td>
                <td class="py-0.5 md:py-1.5 lg:py-2 pr-2 text-right font-bold ${netCls}">${r.net_gex_m}</td>
            </tr>`;
        }).join('');
        if (g.oi_skew) setText('gex-oi-skew', `현재가 기준 · 위: Call OI ${g.oi_skew.call_oi_at_or_above_spot.toLocaleString()} / Put OI ${g.oi_skew.put_oi_at_or_above_spot.toLocaleString()} · 아래: Call OI ${g.oi_skew.call_oi_below_spot.toLocaleString()} / Put OI ${g.oi_skew.put_oi_below_spot.toLocaleString()}`);
        setText('gex-gamma-note', g.gamma_source_note || '');
    } else {
        strikeToggle.classList.add('hidden'); $('gex-strike-panel').classList.add('hidden');
    }

    if (!isNum(spx)) return;
    const emLow = isNum(g.em_pt) ? spx - g.em_pt : null, emHigh = isNum(g.em_pt) ? spx + g.em_pt : null;
    const pts = [spx, emLow, emHigh, g.put_wall, g.call_wall, g.gamma_flip].filter(isNum);
    const minScale = Math.floor((Math.min(...pts) - 10) / 10) * 10, maxScale = Math.ceil((Math.max(...pts) + 10) / 10) * 10;
    const range = maxScale - minScale, getPct = (v) => Math.max(2, Math.min(98, ((v - minScale) / range) * 100));

    setText('scale-min', minScale); setText('scale-max', maxScale);
    setText('em-low-val', isNum(emLow) ? emLow.toFixed(1) : NA); setText('em-high-val', isNum(emHigh) ? emHigh.toFixed(1) : NA);
    setText('marker-current-val', spx.toFixed(1));
    $('marker-current').style.left = `${getPct(spx)}%`;
    if (isNum(emLow)) {
        $('em-range-bar').style.left = `${getPct(emLow)}%`;
        $('em-range-bar').style.width = `${getPct(emHigh) - getPct(emLow)}%`;
    }
    [['marker-put-line', g.put_wall], ['marker-flip-line', g.gamma_flip], ['marker-call-line', g.call_wall]].forEach(([id, v]) => {
        if (isNum(v)) { $(id).style.left = `${getPct(v)}%`; $(id).style.display = 'block'; }
    });
}
