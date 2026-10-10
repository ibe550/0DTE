let currentCvdTf = '10m';
let cachedBars = [];
let defaultCvdLastTime = '--', defaultCvdSub = '--';

function markActive(groupSel, btnClass, tf, activeCls) {
    document.querySelectorAll(groupSel + ' .' + btnClass).forEach((btn) => {
        btn.className = btnClass + ' px-2.5 py-1 rounded text-xs lg:text-sm ' + (btn.getAttribute('data-tf') === tf ? activeCls + ' text-white font-bold shadow' : 'bg-slate-800/80 text-slate-300 hover:bg-slate-700 transition');
    });
}

function changeCvdTimeframe(tf) {
    currentCvdTf = tf;
    markActive('#cvd-tf-group', 'cvd-tf-btn', tf, 'bg-teal-600');
    setText('cvd-title-tf', tf.toUpperCase());
    fetchRealMarketData(true);
}

function inspectCvdBar(idx) {
    if (idx === null || !cachedBars[idx]) {
        $('cvd-inspect-label').innerText = '마지막 봉';
        $('cvd-last-time').innerText = defaultCvdLastTime;
        $('cvd-inspect-sub').innerHTML = defaultCvdSub;
        return;
    }
    const b = cachedBars[idx], d = new Date(b.t * 1000);
    const timeStr = d.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour12: false, hour: '2-digit', minute: '2-digit' }) + ' ET';
    const isLast = (idx === cachedBars.length - 1);
    const rangeHint = isLast && currentCvdTf === '10m' ? ' (15:50~16:00 마감봉)' : (isLast ? ' (마감봉)' : '');
    $('cvd-inspect-label').innerText = '선택 봉';
    $('cvd-last-time').innerText = `${timeStr}${rangeHint}`;
    const flowTag = b.is_bull ? '<span class="text-emerald-400 font-bold">Buy 우세</span>' : '<span class="text-rose-400 font-bold">Sell 우세</span>';
    $('cvd-inspect-sub').innerHTML = `볼륨 <span class="text-slate-100 font-bold">${b.vol}K</span> · CVD <span class="${b.cvd_line >= 0 ? 'text-emerald-400' : 'text-rose-400'} font-bold">${b.cvd_line > 0 ? '+' : ''}${b.cvd_line}K</span> · ${flowTag}`;
}

function renderCvd(c) {
    const pill = $('cvd-status-pill'), priorBadge =$('cvd-prior-badge');
    if (!c) {
        cachedBars = []; setText('cvd-source', NA); setText('cvd-data-time', 'Data as of N/A');
        ['cvd-agg-range', 'cvd-data-desc', 'cvd-last-time', 'cvd-recent-vol', 'cvd-total-vol', 'cvd-summary-text', 'cvd-y-max', 'cvd-y-mid'].forEach(id => setText(id, NA));
        setText('cvd-buy-pct', '▲ Buy N/A'); setText('cvd-sell-pct', '▼ Sell N/A');
        $('cvd-bar-fill').style.width = '0%'; $('cvd-sell-fill').style.width = '0\%';$('cvd-real-bars').innerHTML = ''; $('cvd-line-path').setAttribute('d', '');$('cvd-vertical-grids').innerHTML = '';
        if (priorBadge) priorBadge.classList.add('hidden');
        pill.className = 'text-[10px] sm:text-xs bg-slate-800 text-slate-300 border border-slate-700 px-2 py-0.5 rounded font-semibold flex items-center space-x-1';
        pill.innerHTML = '<span>N/A</span>';
        return;
    }
    cachedBars = c.bars || [];
    if (priorBadge) {
        priorBadge.classList.remove('hidden');
        priorBadge.className = c.is_prior ? 'text-[9px] sm:text-xs bg-amber-950/80 text-amber-300 border border-amber-800/60 px-1.5 py-0.5 rounded font-mono font-bold' : 'text-[9px] sm:text-xs bg-emerald-950/80 text-emerald-300 border border-emerald-800/60 px-1.5 py-0.5 rounded font-mono font-bold';
        priorBadge.innerText = c.is_prior ? `🌙 전일(${c.session_date || '마감'}) 세션 · 09:30 ET 리셋` : '🟢 당일 정규장 실시간';
    }

    const is10mLast = currentCvdTf === '10m' && (c.last_bar_time || '').startsWith('15:50');
    defaultCvdLastTime = is10mLast ? `${c.data_time} (15:50~16:00 마감)` : c.data_time;
    defaultCvdSub = `최근 봉 <span class="text-slate-200">${c.recent_vol}</span> · 합계 <span class="text-slate-200">${c.total_vol}</span>`;
    inspectCvdBar(null);

    setText('cvd-source', c.source); setText('cvd-data-time', `Data as of ${c.data_time}`);
    setText('cvd-agg-range', c.aggregate_range); setText('cvd-data-desc', c.data_desc);
    setText('cvd-buy-pct', `▲ Buy ${c.buy_pct}% (${c.buy_vol})`); setText('cvd-sell-pct', `▼ Sell ${c.sell_pct}% (${c.sell_vol})`);
    $('cvd-bar-fill').style.width = `${c.buy_pct}%`; $('cvd-sell-fill').style.width = `${c.sell_pct}%`;
    setText('cvd-summary-text', c.summary_text);

    const styles = { bull: ['bg-emerald-950/80 text-emerald-300 border-emerald-800/60', '↑'], bear: ['bg-rose-950/80 text-rose-300 border-rose-800/60', '↓'], flat: ['bg-slate-800 text-slate-300 border-slate-700', '↔'] };
    const st = styles[c.tone] || styles.flat;
    pill.className = `text-[10px] sm:text-xs lg:text-sm ${st[0]} border px-2 py-0.5 rounded font-semibold flex items-center space-x-1`;
    pill.innerHTML = `<span>${st[1]} ${c.status}</span>`;

    const bars = cachedBars, maxVol = Math.max(...bars.map(b => b.vol), 0.1), maxCvd = Math.max(...bars.map(b => Math.abs(b.cvd_line)), 1.0);
    const fmtK = v => (v >= 1000 ? `${(v / 1000).toFixed(2)}M` : `${v.toFixed(1)}K`);
    setText('cvd-y-max', fmtK(maxVol)); setText('cvd-y-mid', fmtK(maxVol / 2));

    const AREA_X0 = 40, AREA_W = 440, n = Math.max(bars.length, 1), slot = AREA_W / n;
    const barW = Math.max(0.8, Math.min(24, slot * 0.7)), cx = i => AREA_X0 + i * slot + slot / 2;
    const strokeW = slot < 2.5 ? '0' : '0.7';

    $('cvd-real-bars').innerHTML = bars.map((b, i) => {
        const h = Math.max(1.5, (b.vol / maxVol) * 85), x = cx(i) - barW / 2, y = 110 - h;
        const d = new Date(b.t * 1000), timeStr = d.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour12: false, hour: '2-digit', minute: '2-digit' }) + ' ET';
        const tipRange = (i === bars.length - 1) && currentCvdTf === '10m' ? ' [15:50~16:00 마감봉]' : '';
        return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" fill="${b.is_bull ? '#065f46' : '#881337'}" stroke="${b.is_bull ? '#10b981' : '#f43f5e'}" stroke-width="${strokeW}" class="cursor-pointer transition-opacity hover:opacity-75" onmouseover="inspectCvdBar(${i})" onmouseout="inspectCvdBar(null)" ontouchstart="inspectCvdBar(${i})"><title>[${timeStr}${tipRange}] Vol: ${b.vol}K | CVD: ${b.cvd_line}K</title></rect>`;
    }).join('');

    $('cvd-line-path').setAttribute('d', bars.map((b, i) => `${i === 0 ? 'M' : 'L'} ${cx(i).toFixed(1)} ${(65 - (b.cvd_line / maxCvd) * 40).toFixed(1)}`).join(' '));

    const gridGroup = $('cvd-vertical-grids');
    if (!bars.length) gridGroup.innerHTML = '';
    else {
        let gridHtml = ''; const seenTicks = new Set();
        bars.forEach((b, i) => {
            const d = new Date(b.t * 1000);
            const etHour = parseInt(d.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour12: false, hour: '2-digit' }), 10);
            const etMin = parseInt(d.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour12: false, minute: '2-digit' }), 10);
            const totalMinutes = etHour * 60 + etMin;
            if (totalMinutes % 30 === 0 && !seenTicks.has(totalMinutes)) {
                seenTicks.add(totalMinutes);
                gridHtml += `<line x1="${cx(i).toFixed(1)}" y1="18" x2="${cx(i).toFixed(1)}" y2="110" stroke="#1e293b" stroke-dasharray="2,3" stroke-width="0.8" opacity="0.8"/><text x="${cx(i).toFixed(1)}" y="125" fill="#94a3b8" font-size="9" font-weight="bold" text-anchor="middle" font-family="monospace">${String(etHour).padStart(2, '0')}:${String(etMin).padStart(2, '0')}</text>`;
            }
        });
        const lastBar = bars[bars.length - 1], lastD = new Date(lastBar.t * 1000);
        if (parseInt(lastD.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour12: false, hour: '2-digit' }), 10) === 15 && parseInt(lastD.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour12: false, minute: '2-digit' }), 10) >= 40) {
            gridHtml += `<line x1="480" y1="18" x2="480" y2="110" stroke="#475569" stroke-dasharray="2,2" stroke-width="1"/><text x="478" y="125" fill="#94a3b8" font-size="6.8" text-anchor="end" font-family="monospace" font-weight="bold">16:00</text>`;
        }
        gridGroup.innerHTML = gridHtml;
    }
}
