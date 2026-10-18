const API_URL = 'https://0-dte-seven.vercel.app/api/market-data';
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

// Volume Profile 히스토그램 (7) — 가로 막대, POC 하이라이트, VA 구간 표시
function renderVpHist(vp) {
    const box = document.getElementById('vp-hist');
    if (!box) return;
    const bins = vp && vp.bins ? vp.bins : [];
    if (!bins.length) { box.innerHTML = ''; return; }
    const maxV = Math.max.apply(null, bins.map(b => b.v));
    const poc = vp.poc, val = vp.val, vah = vp.vah;
    // 최대 15행으로 제한해 한 칸씩 크게 표시
    let rows = bins.slice().reverse(); // 고가 → 저가
    while (rows.length > 15) rows = rows.filter((_, i) => i % 2 === 0);
    box.innerHTML = rows.map(b => {
        const w = Math.max(3, Math.round(b.v / maxV * 100));
        const isPoc = b.p === poc;
        const inVA = b.p >= val && b.p <= vah;
        const barCls = isPoc ? 'bg-emerald-400' : (inVA ? 'bg-sky-500' : 'bg-slate-600');
        const lblCls = isPoc ? 'text-emerald-300 font-black' : 'text-slate-100 font-bold';
        const pocTag = isPoc ? '<span class="ml-1 text-[8px] sm:text-[9px] font-black text-emerald-300 bg-emerald-950 border border-emerald-700 px-1 rounded">POC</span>' : '';
        return `<div class="flex items-center gap-1.5 py-[2px]">
            <span class="w-14 shrink-0 text-right font-mono text-[10px] sm:text-xs ${lblCls}">${b.p.toFixed(0)}</span>
            <div class="flex-1 h-[12px] bg-slate-900 rounded-sm overflow-hidden">
                <div class="${barCls} h-full rounded-sm" style="width:${w}%"></div>
            </div>${pocTag}
        </div>`;
    }).join('');
}

async function fetchRealMarketData(force = false) {
    // 인증 전에는 데이터 요청 차단 (잠금화면이 장식이던 문제 해결)
    if (!window.__AUTH_VERIFIED__) return;
    if (inFlight && !force) return;
    inFlight = true;
    const mySeq = ++reqSeq;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 30000); // 30초 여유 확보

    try {
        const w = (typeof optWidth !== 'undefined' && optWidth) ? optWidth : 10;
        const headers = (typeof authHeaders === 'function') ? authHeaders() : {};
        const res = await fetch(`${API_URL}?cvd_tf=${currentCvdTf}&opt_width=${w}`, { signal: ctrl.signal, headers: headers });
        if (res.status === 401) {
            if (mySeq === reqSeq && typeof handleAuthExpired === 'function') handleAuthExpired();
            return;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
        const data = await res.json();
        if (mySeq !== reqSeq || data.status !== 'success') return;

        [
            () => renderShockAlert(data.shock_alert),
            () => renderStatus(data),
            () => renderEconEvents(data.econ_events),
            () => renderRsi(data.rsi),
            () => renderQuote('spx', data.spx, { pct: true }),
            () => renderQuote('es', data.es, { pct: true }),
            () => { renderQuote('vix1d', data.vix1d, { invert: true }); renderQuote('vix', data.vix, { invert: true }); renderIvRank(data.iv_rank); },
            () => renderQuote('mag7', data.mag7, { pct: true }),
            () => renderQuote('wti', data.wti, { pct: true }),
            () => renderQuote('brent', data.brent, { pct: true }),
            () => renderYields(data.yields),
            () => renderPolymarket(data.polymarket),
            () => {
                const vp = data.volume_profile;
                setText('val-price', vp ? vp.val : null); setText('poc-price', vp ? vp.poc : null); setText('vah-price', vp ? vp.vah : null);
                setText('vp-source', vp ? vp.source : NA); setText('vp-timestamp', data.timestamp);
                renderVpHist(vp);
            },
            () => renderGex(data.gex, data.spx ? data.spx.price : null),
            () => renderCvd(data.cvd),
            () => renderCvdOvernight(data.cvd_overnight, data.cvd ? data.cvd.session_mode : null),
            () => renderDirection(data.direction),
        ].forEach(fn => { try { fn(); } catch (e) { console.error('렌더링 에러:', e); } });
    } catch (err) {
        console.error('API Fetch 오류 상세:', err);
        if (mySeq === reqSeq) setText('global-source-badge', 'API 연결 실패 · 재시도 중');
    } finally {
        clearTimeout(timer);
        if (mySeq === reqSeq) inFlight = false;
    }
}

// 폴링 시작점 (auth.js의 로그인 성공/토큰 확인 후에 호출됨)
let _pollStarted = false;
window.startAppPolling = function () {
    if (_pollStarted) { fetchRealMarketData(true); return; }
    _pollStarted = true;
    fetchRealMarketData(true);
    setInterval(() => fetchRealMarketData(false), POLL_MS);
};
