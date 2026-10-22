let _vix1dPrice = null;
let _vixPrice = null;

// ─────────────────────────────────────────────────────────────
// Schwab 우선 · CNBC 폴백 (히스테리시스로 소스 깜빡임 방지)
//  - schwab 모드: 백엔드가 2회 연속 실패(≈10초)해야 CNBC로 전환
//  - cnbc 모드: 백엔드가 3회 연속 성공(≈15초)해야 Schwab으로 복귀
//  - 전환 시 상단(#schwab-status-line)에 안내 문구 표시
// ─────────────────────────────────────────────────────────────
const DUAL_SRC = ['es', 'wti', 'brent'];
const DUAL_LABEL = { es: 'ES', wti: 'WTI', brent: 'BRENT' };
const symMode = { es: 'schwab', wti: 'schwab', brent: 'schwab' };
const backendSeen = { es: false, wti: false, brent: false };
const symMiss = { es: 0, wti: 0, brent: 0 };
const symHit = { es: 0, wti: 0, brent: 0 };
const MISS_TO_FALLBACK = 2;
const HIT_TO_RECOVER = 3;

function refreshSourceNotice() {
    const line = $('schwab-status-line');
    if (!line) return;
    const fb = DUAL_SRC.filter(s => symMode[s] === 'cnbc');
    const fbTxt = fb.length ? `CNBC 데이터로 표시 중: ${fb.map(s => DUAL_LABEL[s]).join(' · ')}` : '';
    if (window.__schwabOk === false) {
        line.classList.remove('hidden');
        line.innerText = fbTxt ? `⚠ ${window.__schwabMsg} → ${fbTxt}` : `⚠ ${window.__schwabMsg}`;
    } else if (fbTxt) {
        line.classList.remove('hidden');
        line.innerText = `⚠ Schwab 데이터를 받지 못해 ${fbTxt}`;
    } else {
        line.classList.add('hidden');
        line.innerText = '';
    }
}

// ─────────────────────────────────────────────────────────────
// 0DTE 변동성 판정: VIX 기간구조(Term Structure) 기반 4단계
//   Ratio = VIX1D ÷ VIX
//   - Ratio ≤ 0.85      : 정상 콘탱고 (1일물 IV가 30일물보다 충분히 낮음)
//   - 0.85 < Ratio < 1.0: 커브 평탄화 (경험적 경계, 0.85는 휴리스틱)
//   - Ratio ≥ 1.0       : 백워데이션(역전) → 절대 VIX 레벨로 2차 판정
//       · VIX < 25      : 역전 주의 (절대 변동성 제한적, 신규 매도 자제)
//       · VIX ≥ 25      : 고변동성 체제 (신규 매도 금지) — 25는 휴리스틱
//   ※ 토/일(ET)에는 금요일 종가 기준 stale 데이터임을 표시
// ─────────────────────────────────────────────────────────────
// IV Rank 표시 (6) — 크레딧 매도 타이밍 잣대 (높을수록 프리미엄 비쌈)
function renderIvRank(iv) {
    const el = document.getElementById('iv-rank-val');
    if (!el) return;
    if (!iv || iv.rank == null) {
        el.innerText = iv && iv.note ? iv.note : 'IVR --';
        el.className = 'text-slate-500 text-[9px] sm:text-[10px]';
        el.title = 'IV Rank (1년) — 데이터 적립 중';
        return;
    }
    const r = iv.rank;
    el.innerText = `IVR ${r}%`;
    el.title = `IV Rank (1년) ${r}% · VIX ${iv.vix} (범위 ${iv.lo}~${iv.hi}, ${iv.days}일)`;
    el.className = 'text-[9px] sm:text-[10px] font-bold ' + (r >= 50 ? 'text-amber-300' : (r >= 25 ? 'text-slate-300' : 'text-slate-500'));
}

function updateVixRatio() {
    const card = $('vix-ratio-card');
    const badge = $('vix-status-badge');
    const desc = $('vix-status-desc');
    const ratioEl = $('vix-ratio-val');
    const dot = $('vix-status-dot');
    if (!card || !badge || !desc || !ratioEl || !dot) return;

    if (!isNum(_vix1dPrice) || !isNum(_vixPrice) || _vixPrice <= 0) {
        badge.className = 'px-2 py-0.5 rounded font-bold text-[9px] sm:text-xs bg-slate-800 text-slate-400 border border-slate-700';
        badge.innerText = '집계 대기';
        desc.innerText = 'VIX 1D 및 VIX 실시간 데이터를 확인하는 중...';
        ratioEl.innerText = 'Ratio --';
        dot.className = 'w-2 h-2 rounded-full bg-slate-500';
        card.className = 'card px-2.5 py-1.5 sm:px-3 sm:py-2 lg:px-4 lg:py-2.5 mb-2 lg:mb-3 flex items-center justify-between text-[10px] sm:text-xs lg:text-sm bg-slate-900/80 border-slate-800';
        return;
    }

    const ratio = _vix1dPrice / _vixPrice;
    ratioEl.innerText = `Ratio ${ratio.toFixed(2)}`;

    // 주말(ET) 판정: VIX/VIX1D는 금요일 종가 기준이므로 stale 표시
    var nowET = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
    var wd = nowET.getDay();
    var staleTag = (wd === 0 || wd === 6) ? ' · 📌 금요일 종가 기준' : '';

    if (ratio <= 0.85) {
        card.className = 'card px-2.5 py-1.5 sm:px-3 sm:py-2 lg:px-4 lg:py-2.5 mb-2 lg:mb-3 flex items-center justify-between text-[10px] sm:text-xs lg:text-sm bg-emerald-950/25 border-emerald-800/70 shadow-sm transition-all';
        dot.className = 'w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]';
        badge.className = 'px-2 py-0.5 rounded font-black text-[9px] sm:text-xs bg-emerald-950 text-emerald-300 border border-emerald-500 tracking-tight';
        badge.innerText = '🟢 스프레드 진입 적격';
        desc.innerHTML = '<span class="text-emerald-300 font-bold">정상 콘탱고</span> · 당일 돌발 급변동 위험 낮음 (프리미엄 수취 최적)' + staleTag;
    } else if (ratio < 1.00) {
        card.className = 'card px-2.5 py-1.5 sm:px-3 sm:py-2 lg:px-4 lg:py-2.5 mb-2 lg:mb-3 flex items-center justify-between text-[10px] sm:text-xs lg:text-sm bg-amber-950/20 border-amber-800/60 transition-all';
        dot.className = 'w-2 h-2 rounded-full bg-amber-400';
        badge.className = 'px-2 py-0.5 rounded font-bold text-[9px] sm:text-xs bg-amber-950 text-amber-300 border border-amber-600 tracking-tight';
        badge.innerText = '🟡 일반 장세 (선별 진입)';
        desc.innerHTML = '<span class="text-amber-300 font-semibold">표준 변동성</span> · Wall 및 EM 이격 15pt 이상 확보 권장' + staleTag;
    } else if (_vixPrice < 25) {
        card.className = 'card px-2.5 py-1.5 sm:px-3 sm:py-2 lg:px-4 lg:py-2.5 mb-2 lg:mb-3 flex items-center justify-between text-[10px] sm:text-xs lg:text-sm bg-orange-950/20 border-orange-800/60 transition-all';
        dot.className = 'w-2 h-2 rounded-full bg-orange-400';
        badge.className = 'px-2 py-0.5 rounded font-bold text-[9px] sm:text-xs bg-orange-950 text-orange-300 border border-orange-600 tracking-tight';
        badge.innerText = '🟠 커브 역전 주의';
        desc.innerHTML = '<span class="text-orange-300 font-bold">변동성 커브 역전</span> · 절대 변동성은 제한적 (신규 매도 자제)' + staleTag;
    } else {
        card.className = 'card px-2.5 py-1.5 sm:px-3 sm:py-2 lg:px-4 lg:py-2.5 mb-2 lg:mb-3 flex items-center justify-between text-[10px] sm:text-xs lg:text-sm bg-rose-950/40 border-rose-600/80 shadow-md transition-all';
        dot.className = 'w-2 h-2 rounded-full bg-rose-500 animate-ping';
        badge.className = 'px-2 py-0.5 rounded font-black text-[9px] sm:text-xs bg-rose-950 text-rose-300 border border-rose-500 tracking-tight animate-pulse';
        badge.innerText = '🚨 크레딧 스프레드 금지';
        desc.innerHTML = '<span class="text-rose-300 font-bold">변동성 커브 역전(백워데이션)</span> · 당일 급변동 경계 (신규 매도 금지)' + staleTag;
    }
}

function renderQuote(pfx, q, opts = {}) {
    // CNBC에서 직접 받아오는 종목들은 백엔드가 빈 값(null)을 보내도 N/A로 지우지 않도록 보호
    if (pfx === 'mag7' || pfx === 'mags' || pfx === 'uso') return;

    // Schwab/CNBC 이중 소스 종목: 히스테리시스로 표시 소스 고정 (깜빡임 방지)
    if (DUAL_SRC.includes(pfx)) {
        const ok = q && isNum(q.price);
        if (symMode[pfx] === 'schwab') {
            if (!ok) {
                symMiss[pfx]++;
                if (symMiss[pfx] >= MISS_TO_FALLBACK) {
                    symMode[pfx] = 'cnbc';
                    symMiss[pfx] = 0; symHit[pfx] = 0;
                    refreshSourceNotice();
                    if (typeof fetchCnbcMacroQuotes === 'function') fetchCnbcMacroQuotes();
                }
                return; // 1회성 실패는 기존 표시 유지
            }
            symMiss[pfx] = 0;
            backendSeen[pfx] = true;
        } else {
            // cnbc 모드: 백엔드가 연속 3회 유효해야 Schwab으로 복귀
            if (ok) {
                symHit[pfx]++;
                if (symHit[pfx] < HIT_TO_RECOVER) return;
                symMode[pfx] = 'schwab';
                symHit[pfx] = 0; symMiss[pfx] = 0;
                backendSeen[pfx] = true;
                refreshSourceNotice();
            } else {
                symHit[pfx] = 0;
                return;
            }
        }
    }

    if (!q) {
        setText(pfx + '-price', NA); setText(pfx + '-change', NA); setText(pfx + '-source', NA);
        setTone(pfx + '-price', 'text-slate-500'); setTone(pfx + '-change', 'text-slate-500');
        if (pfx === 'vix1d') { _vix1dPrice = null; updateVixRatio(); }
        if (pfx === 'vix') { _vixPrice = null; updateVixRatio(); }
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

    if (pfx === 'vix1d') { _vix1dPrice = q.price; updateVixRatio(); }
    if (pfx === 'vix') { _vixPrice = q.price; updateVixRatio(); }
}

function renderYields(y) {
    return;
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
    else if (r.val <= 45) { statusText = '하락'; colorCls = 'bg-indigo-950/70 text-indigo-300 border-indigo-800/80'; }
    badge.className = `font-mono px-1.5 py-0.5 rounded font-bold border ${colorCls} text-[9px] lg:text-xs`;
    badge.innerText = `RSI ${val} (${statusText})`;
}

// ─────────────────────────────────────────────────────────────
// 장중 쇼크 소리 알림 (Web Audio API, 외부 파일 불필요)
// 브라우저 정책상 사용자 제스처 후에만 동작 → 헤더 🔊 토글로 활성화
// ─────────────────────────────────────────────────────────────
let soundOn = false;
let lastShockId = null;
function _beep(freq, dur, delay) {
    try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        const ctx = new Ctx();
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.connect(g); g.connect(ctx.destination);
        o.frequency.value = freq; o.type = 'sine';
        const t = ctx.currentTime + (delay || 0);
        g.gain.setValueAtTime(0.001, t);
        g.gain.exponentialRampToValueAtTime(0.4, t + 0.02);
        g.gain.exponentialRampToValueAtTime(0.001, t + dur);
        o.start(t); o.stop(t + dur + 0.05);
    } catch (e) {}
}
function shockBeep() { _beep(880, 0.22, 0); _beep(880, 0.22, 0.28); _beep(1318, 0.4, 0.56); }
function initSoundToggle() {
    const btn = document.getElementById('sound-toggle');
    if (!btn || btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => {
        soundOn = !soundOn;
        btn.innerText = soundOn ? '🔊' : '🔇';
        btn.title = soundOn ? '쇼크 소리 알림 끄기' : '쇼크 소리 알림 켜기';
        if (soundOn) _beep(880, 0.15, 0); // 활성화 확인음
    });
}
document.addEventListener('DOMContentLoaded', initSoundToggle);

function renderShockAlert(alert) {
    const banner = $('shock-alert-banner');
    if (!banner || !alert || !alert.active) {
        if (banner) banner.classList.add('hidden');
        return;
    }
    // 새 쇼크 발생 시 소리 알림 (같은 쇼크 반복 재생 방지)
    const alertId = alert.timestamp || alert.title || '';
    if (soundOn && alertId && alertId !== lastShockId) {
        lastShockId = alertId;
        shockBeep();
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
    window.__schwabOk = (data.schwab_status || '').startsWith('연결됨');
    window.__schwabMsg = data.schwab_status || '';
    refreshSourceNotice();
}

// ─────────────────────────────────────────────────────────────
// ES · WTI · BRENT · MAG7 · USO · 미 국채 3종(3M·10Y·30Y) CNBC 통합 연동
// ─────────────────────────────────────────────────────────────
function applyMacroCardStyle(prefix, price, change, changePct, sourceLabel, extraSubText, useComma) {
    // 이중 소스 종목은 Schwab 모드에서 CNBC가 아예 그리지 않음 (기존 가드는 Schwab 표시 후 덮어쓰기만 막아
    // 새로고침 시 CNBC 선행 페인트 → Schwab 덮어쓰기 깜빡임이 남았음. Schwab 실패 시에는 모드 전환 후 CNBC가 그림)
    if (DUAL_SRC.includes(prefix) && symMode[prefix] === 'schwab') return;
    var priceEl = document.getElementById(prefix + '-price');
    var changeEl = document.getElementById(prefix + '-change');
    var srcEl = document.getElementById(prefix + '-source');
    if (!priceEl || !changeEl || price === null || price === undefined || isNaN(price)) return;

    var pNum = Number(price);
    var cNum = Number(change || 0);
    var pctNum = Number(changePct || 0);
    var sign = cNum > 0 ? '+' : '';

    priceEl.textContent = useComma
        ? pNum.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : pNum.toFixed(2);

    var chgStr = sign + cNum.toFixed(2) + ' (' + sign + pctNum.toFixed(2) + '%)';
    changeEl.textContent = extraSubText ? (chgStr + ' · ' + extraSubText) : chgStr;

    var tone = cNum > 0 ? 'text-emerald-400' : (cNum < 0 ? 'text-rose-400' : 'text-slate-200');
    setTone(prefix + '-price', tone);
    setTone(prefix + '-change', tone);

    if (srcEl && sourceLabel) srcEl.textContent = sourceLabel;
}

function applyYieldCardStyle(idPrefix, yieldVal, changeVal, sourceLabel) {
    if (yieldVal === null || yieldVal === undefined || isNaN(yieldVal)) return;
    var bp = Math.round((changeVal || 0) * 100);
    var bpSign = bp > 0 ? '+' : '';

    setText(idPrefix, yieldVal.toFixed(3) + '%');
    setTone(idPrefix, 'text-slate-200');
    setText(idPrefix + '-src', sourceLabel);
    setText(idPrefix + '-chg', bpSign + bp + ' bp');
    setTone(idPrefix + '-chg', bp > 0 ? 'text-rose-400' : (bp < 0 ? 'text-emerald-400' : 'text-slate-400'));
}

function handleEtfWithExtended(prefix, baseLabel, q, regPrice, regChg, regPct) {
    var ext = q.ExtendedMktQuote;
    if (q.curmktstatus && q.curmktstatus !== 'REG_MKT' && ext && ext.last) {
        var extPrice = parseFloat(String(ext.last).replace(/[^0-9.-]/g, ''));
        var extChg = parseFloat(String(ext.change || '0').replace(/[^0-9.-]/g, ''));
        var extPct = parseFloat(String(ext.change_pct || '0').replace(/[^0-9.-]/g, ''));
        if (!isNaN(extPrice) && extPrice > 0) {
            var tag = ext.type === 'PRE' ? 'PRE' : 'AH';
            applyMacroCardStyle(prefix, extPrice, extChg, extPct, 'CNBC (' + tag + ')', '종가 ' + regPrice.toFixed(2), false);
            return;
        }
    }
    applyMacroCardStyle(prefix, regPrice, regChg, regPct, 'CNBC (' + baseLabel + ')', null, false);
}

function fetchCnbcMacroQuotes() {
    // ES(@SP.1), WTI(@CL.1), BRENT(@LCO.1) 포함 8종목 모두 한 번에 호출하여 N/A 원천 방지
    var url = 'https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=@SP.1%7CMAGS%7C@CL.1%7C@LCO.1%7CUSO%7CUS3M%7CUS10Y%7CUS30Y&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json';

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var list = d && d.FormattedQuoteResult && d.FormattedQuoteResult.FormattedQuote;
            if (!Array.isArray(list)) return;

            var y3mVal = null;
            var y10Val = null;
            var magPrefix = document.getElementById('mag7-price') ? 'mag7' : 'mags';

            list.forEach(function(q) {
                if (!q || !q.symbol || !q.last) return;
                var sym = q.symbol.toUpperCase();
                var regPrice = parseFloat(String(q.last).replace(/[^0-9.-]/g, ''));
                var regChg = parseFloat(String(q.change || '0').replace(/[^0-9.-]/g, ''));
                var regPct = parseFloat(String(q.change_pct || '0').replace(/[^0-9.-]/g, ''));

                if (sym === '@SP.1') {
                    applyMacroCardStyle('es', regPrice, regChg, regPct, 'CNBC (ES)', null, true);
                } else if (sym === 'MAGS') {
                    handleEtfWithExtended(magPrefix, 'MAGS', q, regPrice, regChg, regPct);
                } else if (sym === '@CL.1') {
                    applyMacroCardStyle('wti', regPrice, regChg, regPct, 'CNBC (CL)', null, false);
                } else if (sym === '@LCO.1') {
                    applyMacroCardStyle('brent', regPrice, regChg, regPct, 'CNBC (BZ)', null, false);
                } else if (sym === 'USO') {
                    handleEtfWithExtended('uso', 'USO', q, regPrice, regChg, regPct);
                } else if (sym === 'US3M') {
                    y3mVal = regPrice;
                    applyYieldCardStyle('yield-3m', regPrice, regChg, 'CNBC (US3M)');
                } else if (sym === 'US10Y') {
                    y10Val = regPrice;
                    applyYieldCardStyle('yield-10y', regPrice, regChg, 'CNBC (US10Y)');
                } else if (sym === 'US30Y') {
                    applyYieldCardStyle('yield-30y', regPrice, regChg, 'CNBC (US30Y)');
                }
            });

            if (y10Val !== null && y3mVal !== null && !isNaN(y10Val) && !isNaN(y3mVal)) {
                var spreadBp = Math.round((y10Val - y3mVal) * 100);
                var spSign = spreadBp > 0 ? '+' : '';
                setText('yield-spread', spSign + spreadBp + ' bp');
                setTone('yield-spread', spreadBp < 0 ? 'text-rose-400' : 'text-emerald-400');
            }
        })
        .catch(function() {});
}

document.addEventListener('DOMContentLoaded', function() {
    fetchCnbcMacroQuotes();
    setInterval(fetchCnbcMacroQuotes, 15000);
});
