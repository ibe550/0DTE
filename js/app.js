const API_URL = 'https://0-dte-seven.vercel.app/api/market-data';
const POLL_MS = 10000;
const FULL_POLL_MS = 30000; // 분석(무거운 조회) 폴링 주기 — 시세 폴링과 분리
const _fullState = { inFlight: false, seq: 0 };
const _qState = { inFlight: false, seq: 0 };

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

let _revPrevConfAt = undefined;
function fmtAgo(sec) {
    if (sec == null) return '기록 없음';
    if (sec < 90) return '방금 전';
    if (sec < 3600) return Math.round(sec / 60) + '분 전';
    if (sec < 86400) return Math.round(sec / 3600) + '시간 전';
    return Math.round(sec / 86400) + '일 전';
}

let _presWired = false;
function renderPresence(p) {
    const chip = $('presence-chip');
    const pop = $('presence-pop');
    if (!chip) return;
    if (!p || !p.admin || !Array.isArray(p.users)) {
        chip.classList.add('hidden');
        if (pop) pop.classList.add('hidden');
        return;
    }
    const on = p.users.filter(u => u.online).map(u => u.name);
    // 칩은 공간 절약: 최대 2명까지 이름, 나머지는 +N
    chip.textContent = '👥 ' + (on.length
        ? on.slice(0, 2).join(' · ') + (on.length > 2 ? ` +${on.length - 2}` : '')
        : '접속자 없음');
    chip.title = p.users.map(u => u.online ? `${u.name} · 접속 중` : `${u.name} · ${fmtAgo(u.ago_sec)}`).join('\n');
    chip.classList.remove('hidden');
    if (pop) {
        pop.innerHTML = p.users.map(u =>
            `<div class="flex items-center justify-between gap-3 py-0.5">
                <span class="${u.online ? 'text-emerald-300 font-semibold' : 'text-slate-400'}">${u.online ? '🟢' : '⚪'} ${u.name}</span>
                <span class="text-slate-500">${u.online ? '접속 중' : fmtAgo(u.ago_sec)}</span>
            </div>`).join('');
    }
    if (!_presWired) {
        _presWired = true;
        chip.addEventListener('click', (e) => {
            e.stopPropagation();
            if (pop) pop.classList.toggle('hidden');
        });
        document.addEventListener('click', (e) => {
            if (pop && !pop.classList.contains('hidden') && e.target !== chip && !pop.contains(e.target)) {
                pop.classList.add('hidden');
            }
        });
    }
}

function renderReversal(r) {
    const panel = $('rev-panel');
    if (!panel) return;
    if (!r || !r.available) { panel.style.display = 'none'; _revPrevConfAt = undefined; return; }
    panel.style.display = 'block';
    const badge = $('rev-badge');
    const segTxt = r.seg_dir === 'up' ? `현재 추세 ▲ 상승 · ${r.seg_from || ''}부터 ${r.seg_change > 0 ? '+' : ''}${r.seg_change}pt`
        : (r.seg_dir === 'down' ? `현재 추세 ▼ 하락 · ${r.seg_from || ''}부터 ${r.seg_change}pt` : '뚜렷한 추세 없음');
    const defTxt = (r.defense != null && r.seg_dir) ? ` · 방어선 ${Number(r.defense).toLocaleString()}` : '';
    const flips = r.flips || [];
    const lf = flips.length ? flips[flips.length - 1] : null;
    const flipTxt = lf ? ` · 최근 전환 ${lf.at} ${lf.from === 'up' ? '상승' : '하락'}→${lf.to === 'up' ? '상승' : '하락'}` : '';
    const base = (r.state === 'flat' || r.state === 'forming') ? (r.note || segTxt)
        : ((r.note || '').includes('무효') ? `${r.note} · ${segTxt}${defTxt}` : `${segTxt}${defTxt}`);
    setText('rev-line1', base + flipTxt);
    const B = {
        flat: ['횡보 · 감지 대기', 'bg-slate-800 text-slate-400'],
        forming: ['추세 형성 중', 'bg-sky-950 text-sky-300 border border-sky-800'],
        hold: ['추세 유지', 'bg-slate-800 text-slate-200'],
        watch: [`⚠️ 전환 조짐 (${r.sig_count}/${r.sig_total})`, 'bg-amber-950 text-amber-300 border border-amber-700'],
        warn: [`🚨 전환 경보 (${r.sig_count}/${r.sig_total})`, 'bg-orange-950 text-orange-300 border border-orange-700'],
        confirmed: [`🔄 ${r.new_dir === 'up' ? '상승' : '하락'} 전환 확정${r.confirmed_at ? ' ' + r.confirmed_at : ''}`,
            r.new_dir === 'up' ? 'bg-emerald-600 text-white' : 'bg-rose-600 text-white'],
    };
    const b = B[r.state] || ['--', 'bg-slate-800 text-slate-300'];
    badge.innerText = b[0]; badge.className = `text-[10px] sm:text-xs font-black px-1.5 py-0.5 rounded ${b[1]}`;
    const chip = (label, v) => {
        if (v === true) return `<span class="text-[9px] sm:text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">✓ ${label}</span>`;
        if (v === false) return `<span class="text-[9px] sm:text-[10px] font-bold px-1.5 py-0.5 rounded bg-slate-900 text-slate-500 border border-slate-800">✕ ${label}</span>`;
        return `<span class="text-[9px] sm:text-[10px] font-bold px-1.5 py-0.5 rounded bg-slate-900 text-slate-600 border border-dashed border-slate-800">… ${label}</span>`;
    };
    const s = r.signals || {};
    $('rev-sigs').innerHTML = chip('VWAP 반대 마감', s.vwap) + chip('구조 방어선 돌파', s.orr) + chip('CVD 반전', s.cvd);
    const ev = $('rev-event'), ne = r.next_event;
    if (ne) {
        ev.style.display = 'block';
        ev.innerText = ne.mins > 0 ? `⚠️ ${ne.time} 지표 임박 (${ne.mins}분 전): ${ne.title} — 전환 주의 구간`
                                   : `⚠️ ${ne.time} 지표 발표 직후: ${ne.title}`;
    } else ev.style.display = 'none';
    // 새 확정 발생 시 1회 소리 (기존 🔊 토글 연동, 첫 렌더에서는 울리지 않음)
    if (_revPrevConfAt !== undefined && r.confirmed_at && r.confirmed_at !== _revPrevConfAt
        && typeof soundOn !== 'undefined' && soundOn && typeof _beep === 'function') {
        if (r.new_dir === 'up') { _beep(660, 0.18, 0); _beep(990, 0.3, 0.22); }
        else { _beep(990, 0.18, 0); _beep(660, 0.3, 0.22); }
    }
    if (r.confirmed_at) _revPrevConfAt = r.confirmed_at;
    else if (_revPrevConfAt === undefined) _revPrevConfAt = null;
}

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

async function fetchRealMarketData(force = false, part = 'full') {
    // 인증 전에는 데이터 요청 차단 (잠금화면이 장식이던 문제 해결)
    if (!window.__AUTH_VERIFIED__) return;
    const isQ = part === 'quotes';
    const st = isQ ? _qState : _fullState;
    if (st.inFlight && !force) return;
    st.inFlight = true;
    const mySeq = ++st.seq;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 30000); // 30초 여유 확보

    try {
        const headers = (typeof authHeaders === 'function') ? authHeaders() : {};
        const url = isQ ? `${API_URL}?part=quotes` : `${API_URL}?cvd_tf=${currentCvdTf}`;
        const res = await fetch(url, { signal: ctrl.signal, headers: headers });
        if (res.status === 401) {
            if (mySeq === st.seq && typeof handleAuthExpired === 'function') handleAuthExpired();
            return;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
        const data = await res.json();
        if (mySeq !== st.seq || data.status !== 'success') return;

        const quoteRenderers = [
            () => renderStatus(data),
            () => renderPresence(data.presence),
            () => renderQuote('spx', data.spx, { pct: true }),
            () => renderQuote('es', data.es, { pct: true }),
            () => { renderQuote('vix1d', data.vix1d, { invert: true }); renderQuote('vix', data.vix, { invert: true }); renderIvRank(data.iv_rank); },
            () => renderQuote('mag7', data.mag7, { pct: true }),
            () => renderQuote('wti', data.wti, { pct: true }),
            () => renderQuote('brent', data.brent, { pct: true }),
            () => renderYields(data.yields),
        ];
        const fullRenderers = [
            () => renderShockAlert(data.shock_alert),
            () => renderEconEvents(data.econ_events),
            () => renderRsi(data.rsi),
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
            () => renderReversal(data.reversal),
        ];
        (isQ ? quoteRenderers : [...quoteRenderers, ...fullRenderers])
            .forEach(fn => { try { fn(); } catch (e) { console.error('렌더링 에러:', e); } });
    } catch (err) {
        console.error('API Fetch 오류 상세:', err);
        if (mySeq === st.seq) setText('global-source-badge', 'API 연결 실패 · 재시도 중');
    } finally {
        clearTimeout(timer);
        if (mySeq === st.seq) st.inFlight = false;
    }
}

// 폴링 시작점 (auth.js의 로그인 성공/토큰 확인 후에 호출됨)
let _pollStarted = false;
window.startAppPolling = function () {
    if (_pollStarted) { fetchRealMarketData(true); return; }
    _pollStarted = true;
    fetchRealMarketData(true);
    fetchRealMarketData(true, 'quotes');
    setInterval(() => fetchRealMarketData(false), FULL_POLL_MS);
    setInterval(() => fetchRealMarketData(false, 'quotes'), POLL_MS);
};
