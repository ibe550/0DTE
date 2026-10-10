const API_URL = '[https://0-dte-seven.vercel.app/api/market-data](https://0-dte-seven.vercel.app/api/market-data)';
const POLL_MS = 5000;
let inFlight = false;
let reqSeq = 0;

function toggleDetailEvidence() {
    const panel = $('detail-evidence-panel'), arrow = $('evidence-arrow'), txt =$('evidence-toggle-text');
    if (panel.classList.contains('hidden')) {
        panel.classList.remove('hidden'); arrow.style.transform = 'rotate(180deg)'; txt.innerText = '클릭하여 접기';
    } else {
        panel.classList.add('hidden'); arrow.style.transform = 'rotate(0deg)'; txt.innerText = '클릭하여 펼치기';
    }
}

function renderDirection(d) {
    const tfKeys = ['5m', '1m', '15m', '1h'], list = $('evidence-list');
    if (!d || !d.available) {
        setText('dir-main-status', NA); setText('dir-top-score', '종합 점수 N/A');
        setText('dir-summary', (d && d.reason) ? d.reason : '실시간 봉 데이터를 가져오지 못해 방향을 판단할 수 없습니다.');
        setText('dir-source', 'Source N/A'); setText('tf-match-pct', NA); setTone('dir-top-score', 'text-slate-500');
        $('dir-head').className = 'flex items-center space-x-1.5 text-xs sm:text-sm lg:text-base font-bold text-slate-300';
        $('dir-gauge-pin').style.left = '50\%';$('dir-gauge-pin').className = 'absolute top-0 bottom-0 w-2 md:w-2.5 bg-slate-400 rounded shadow';
        tfKeys.forEach(k => { setText(`tf-${k}-status`, NA); setText(`tf-${k}-score`, NA); setTone(`tf-${k}-status`, 'text-slate-500'); setTone(`tf-${k}-label`, 'text-slate-300'); });
        list.innerHTML = '';
        return;
    }
    const tc = toneByName(d.tone);
    setText('dir-main-status', d.status); setText('dir-top-score', `종합 점수 ${d.score_text}`); setTone('dir-top-score', tc);
    $('dir-head').className = `flex items-center space-x-1.5 text-xs sm:text-sm lg:text-base font-bold ${tc}`;
    setText('dir-summary', d.summary); setText('dir-source', `Source ${d.source}`); $('dir-source').title = d.source;
    setText('tf-match-pct', d.match_pct);
    $('dir-gauge-pin').style.left = `${Math.max(2, Math.min(98, ((d.score + 6) / 12) * 100))}%`;
    $('dir-gauge-pin').className = `absolute top-0 bottom-0 w-2 md:w-2.5 rounded shadow ${d.tone === 'bull' ? 'bg-emerald-400' : (d.tone === 'bear' ? 'bg-rose-400' : 'bg-slate-400')}`;

    tfKeys.forEach(k => {
        const t = d.tfs ? d.tfs[k] : null;
        if (!t) { setText(`tf-${k}-status`, '데이터 부족'); setText(`tf-${k}-score`, NA); setTone(`tf-${k}-status`, 'text-slate-500'); setTone(`tf-${k}-label`, 'text-slate-300'); return; }
        setText(`tf-${k}-status`, t.status); setText(`tf-${k}-score`, sgn(t.score, 1));
        setTone(`tf-${k}-status`, toneByName(t.tone)); setTone(`tf-${k}-label`, toneByName(t.tone));
    });

    const dot = { bull: 'bg-emerald-400', bear: 'bg-rose-400', flat: 'bg-slate-400', na: 'bg-slate-600' };
    const txt = { bull: 'text-emerald-400', bear: 'text-rose-400', flat: 'text-slate-300', na: 'text-slate-500' };
    list.innerHTML = (d.evidence || []).map(e => `<div class="bg-slate-950 p-2 sm:p-2.5 rounded border border-slate-800 space-y-0.5"><div class="flex items-center space-x-1 font-bold ${txt[e.signal] || txt.na}"><span class="w-1.5 h-1.5 rounded-full ${dot[e.signal] || dot.na} inline-block"></span><span>${e.title}</span></div><div class="text-slate-300 pl-3">${e.text}</div></div>`).join('');
}

async function fetchRealMarketData(force = false) {
    if (inFlight && !force) return;
    inFlight = true;
    const mySeq = ++reqSeq, ctrl = new AbortController(), timer = setTimeout(() => ctrl.abort(), 15000);
    try {
        const res = await fetch(`${API_URL}?cvd_tf=${currentCvdTf}`, { signal: ctrl.signal });
        const data = await res.json();
        if (mySeq !== reqSeq || data.status !== 'success') return;

        [
            () => renderShockAlert(data.shock_alert),
            () => renderStatus(data),
            () => renderEconEvents(data.econ_events),
            () => renderRsi(data.rsi),
            () => renderQuote('spx', data.spx, { pct: true }),
            () => renderQuote('es', data.es, { pct: true }),
            () => { renderQuote('vix1d', data.vix1d, { invert: true }); renderQuote('vix', data.vix, { invert: true }); },
            () => renderQuote('mag7', data.mag7, { pct: true }),
            () => renderQuote('wti', data.wti, { pct: true }),
            () => renderQuote('brent', data.brent, { pct: true }),
            () => renderYields(data.yields),
            () => renderPolymarket(data.polymarket),
            () => {
                const vp = data.volume_profile;
                setText('val-price', vp ? vp.val : null); setText('poc-price', vp ? vp.poc : null); setText('vah-price', vp ? vp.vah : null);
                setText('vp-source', vp ? vp.source : NA); setText('vp-timestamp', data.timestamp);
            },
            () => renderGex(data.gex, data.spx ? data.spx.price : null),
            () => renderCvd(data.cvd),
            () => renderDirection(data.direction),
        ].forEach(fn => { try { fn(); } catch (e) { console.error('렌더링 에러:', e); } });
    } catch (err) {
        if (mySeq === reqSeq) setText('global-source-badge', 'API 연결 실패 · 재시도 중');
    } finally {
        clearTimeout(timer);
        if (mySeq === reqSeq) inFlight = false;
    }
}

fetchRealMarketData(true);
setInterval(() => fetchRealMarketData(false), POLL_MS);
