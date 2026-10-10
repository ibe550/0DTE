let gexStrikesExpanded = false;
let currentGexData = null;
let currentSpotPrice = null;

function toggleGexStrikes() {
    gexStrikesExpanded = !gexStrikesExpanded;
    const panel = $('gex-strike-panel');
    const arrow = $('gex-strike-arrow');
    const txt = $('gex-strike-toggle-text');
    if (!panel) return;
    if (gexStrikesExpanded) {
        panel.classList.remove('hidden');
        if (arrow) arrow.classList.add('rotate-180');
        if (txt) txt.innerText = '클릭하여 차트 접기';
        drawGexBarChart();
    } else {
        panel.classList.add('hidden');
        if (arrow) arrow.classList.remove('rotate-180');
        if (txt) txt.innerText = '클릭하여 차트 펼치기';
    }
}

// ─────────────────────────────────────────────────────────────
// 0DTE GEX 대칭 막대 그래프 렌더링 엔진
// ─────────────────────────────────────────────────────────────
let chartBars = [];

function drawGexBarChart() {
    const canvas = $('gex-chart-canvas');
    if (!canvas || !currentGexData || !currentGexData.by_strike || !currentGexData.by_strike.length) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const padTop = 32;
    const padBottom = 28;
    const padX = 24;
    const drawH = h - padTop - padBottom;
    const midY = padTop + drawH / 2; // Y = 0 중심선

    const strikes = [...currentGexData.by_strike].sort((a, b) => a.strike - b.strike);
    
    // 최대 Y 스케일 산출
    let maxVal = 10;
    strikes.forEach(s => {
        const cGex = s.call_gex_m ?? Math.max(0, (s.net_gex_m || 0));
        const pGex = s.put_gex_m ?? Math.abs(Math.min(0, (s.net_gex_m || 0)));
        if (cGex > maxVal) maxVal = cGex;
        if (pGex > maxVal) maxVal = pGex;
    });
    maxVal = maxVal * 1.15; // 상하 여백 버퍼

    ctx.clearRect(0, 0, w, h);

    // 1. 기준선 (Zero Line & Grid)
    ctx.strokeStyle = 'rgba(51, 65, 85, 0.6)';
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(padX, midY);
    ctx.lineTo(w - padX, midY);
    ctx.stroke();

    // Y축 가이드 텍스트
    ctx.fillStyle = '#64748b';
    ctx.font = '10px monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`+${maxVal.toFixed(0)}M`, 4, padTop + 10);
    ctx.fillText(`-${maxVal.toFixed(0)}M`, 4, h - padBottom - 4);
    ctx.fillText(`0`, 8, midY + 3);

    // 2. 행사가별 대칭 바 렌더링
    const barWidth = Math.max(4, Math.min(18, (w - padX * 2) / strikes.length - 3));
    const stepX = (w - padX * 2) / strikes.length;
    chartBars = [];

    strikes.forEach((s, idx) => {
        const x = padX + (idx + 0.5) * stepX;
        const cGex = s.call_gex_m ?? Math.max(0, ((s.abs_gex_m + s.net_gex_m) / 2) || 0);
        const pGex = s.put_gex_m ?? Math.max(0, ((s.abs_gex_m - s.net_gex_m) / 2) || 0);

        const callBarH = (cGex / maxVal) * (drawH / 2);
        const putBarH = (pGex / maxVal) * (drawH / 2);

        // Call GEX 상방 막대 (초록)
        if (callBarH > 0) {
            ctx.fillStyle = '#10b981';
            ctx.fillRect(x - barWidth / 2, midY - callBarH, barWidth, callBarH);
        }

        // Put GEX 하방 막대 (붉은색)
        if (putBarH > 0) {
            ctx.fillStyle = '#f43f5e';
            ctx.fillRect(x - barWidth / 2, midY, barWidth, putBarH);
        }

        // X축 행사가 라벨 (일정 간격으로만 표시)
        if (strikes.length <= 15 || idx % Math.ceil(strikes.length / 12) === 0) {
            ctx.fillStyle = '#94a3b8';
            ctx.font = '9px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(s.strike.toString(), x, h - 8);
        }

        chartBars.push({ x, barWidth, strikeData: s, cGex, pGex });
    });

    // 3. 현재 지수(SPX Current Spot) 수직선 오버레이
    if (currentSpotPrice && strikes.length >= 2) {
        const minK = strikes[0].strike;
        const maxK = strikes[strikes.length - 1].strike;
        if (currentSpotPrice >= minK && currentSpotPrice <= maxK) {
            const spotPct = (currentSpotPrice - minK) / (maxK - minK);
            const spotX = padX + spotPct * (w - padX * 2);

            // 세로 점선
            ctx.strokeStyle = '#818cf8';
            ctx.lineWidth = 1.5;
            ctx.setLineDash([4, 3]);
            ctx.beginPath();
            ctx.moveTo(spotX, 4);
            ctx.lineTo(spotX, h - padBottom);
            ctx.stroke();
            ctx.setLineDash([]);

            // 현재가 배지 (상단 헤더)
            const badgeTxt = currentSpotPrice.toFixed(2);
            ctx.font = 'bold 10px monospace';
            const txtW = ctx.measureText(badgeTxt).width + 8;
            ctx.fillStyle = '#312e81';
            ctx.strokeStyle = '#6366f1';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.roundRect(spotX - txtW / 2, 4, txtW, 16, 3);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = '#ffffff';
            ctx.textAlign = 'center';
            ctx.fillText(badgeTxt, spotX, 16);
        }
    }
}

// ─────────────────────────────────────────────────────────────
// 마우스/터치 인터랙티브 툴팁 이벤트
// ─────────────────────────────────────────────────────────────
function initChartInteraction() {
    const canvas = $('gex-chart-canvas');
    const tt = $('gex-chart-tooltip');
    if (!canvas || !tt) return;

    function handlePointer(clientX, clientY) {
        if (!chartBars.length) return;
        const rect = canvas.getBoundingClientRect();
        const mouseX = clientX - rect.left;
        const mouseY = clientY - rect.top;

        // 가장 가까운 행사가 탐색
        let closest = null;
        let minDiff = Infinity;
        chartBars.forEach(b => {
            const diff = Math.abs(b.x - mouseX);
            if (diff < minDiff) {
                minDiff = diff;
                closest = b;
            }
        });

        if (closest && minDiff < 28) {
            const s = closest.strikeData;
            setText('tt-strike', `${s.strike} Strike`);
            const netVal = s.net_gex_m || (closest.cGex - closest.pGex);
            const netEl = $('tt-net');
            if (netEl) {
                netEl.innerText = `${netVal > 0 ? '+' : ''}${netVal.toFixed(1)}M`;
                netEl.className = `font-bold ${netVal >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;
            }
            setText('tt-calls', `+${closest.cGex.toFixed(1)}M`);
            setText('tt-puts', `-${closest.pGex.toFixed(1)}M`);
            setText('tt-abs', `${(s.abs_gex_m || (closest.cGex + closest.pGex)).toFixed(1)}M`);
            setText('tt-call-oi', (s.call_oi || 0).toLocaleString());
            setText('tt-put-oi', (s.put_oi || 0).toLocaleString());
            setText('tt-call-vol', (s.call_vol || 0).toLocaleString());
            setText('tt-put-vol', (s.put_vol || 0).toLocaleString());

            // 툴팁 위치 배치 (화면 우측 잘림 방지)
            tt.classList.remove('hidden');
            let ttLeft = closest.x + 12;
            if (ttLeft + 180 > rect.width) ttLeft = closest.x - 190;
            let ttTop = Math.max(10, mouseY - 60);
            if (ttTop + 180 > rect.height) ttTop = rect.height - 185;

            tt.style.left = `${ttLeft}px`;
            tt.style.top = `${ttTop}px`;
        } else {
            tt.classList.add('hidden');
        }
    }

    canvas.addEventListener('mousemove', (e) => handlePointer(e.clientX, e.clientY));
    canvas.addEventListener('mouseleave', () => tt.classList.add('hidden'));
    canvas.addEventListener('touchmove', (e) => {
        if (e.touches.length > 0) handlePointer(e.touches[0].clientX, e.touches[0].clientY);
    }, { passive: true });
    canvas.addEventListener('touchend', () => tt.classList.add('hidden'));
    window.addEventListener('resize', drawGexBarChart);
}

document.addEventListener('DOMContentLoaded', initChartInteraction);

// ─────────────────────────────────────────────────────────────
// 기존 GEX 데이터 수신 및 렌더링 파이프라인
// ─────────────────────────────────────────────────────────────
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
        setText('gex-abs-pin', NA);
        if (note) { note.classList.remove('hidden'); note.innerText = (g && g.reason) || 'GEX 데이터를 불러올 수 없습니다.'; }
        renderSpreadOptimizer(null);
        return;
    }
    if (note) note.classList.add('hidden');
    currentGexData = g;
    currentSpotPrice = isNum(g.gamma_flip) ? g.gamma_flip : null;

    setText('gex-source', srcShort(g.source));
    const is0dte = g.is_0dte ? '0DTE 당일 만기' : '익일 만기';
    setText('gex-meta', `${g.expiration || ''} (${is0dte}) · 행사가 ${g.strike_count || 0}개`);
    setText('gex-em', g.expected_move || NA);
    setText('gex-put-wall', isNum(g.put_wall) ? fmt(g.put_wall, 1) : NA);
    setText('gex-flip', isNum(g.gamma_flip) ? fmt(g.gamma_flip, 1) : NA);
    setText('gex-call-wall', isNum(g.call_wall) ? fmt(g.call_wall, 1) : NA);

    // Absolute Gamma Pin Strike
    const pinText = isNum(g.abs_pin_strike) ? `${fmt(g.abs_pin_strike, 0)} (${g.abs_pin_val}M$)` : NA;
    setText('gex-abs-pin', pinText);

    const regime = $('gex-regime');
    if (regime && g.regime_text) {
        regime.classList.remove('hidden');
        regime.innerText = `Net GEX: ${g.net_gex || '--'} · ${g.regime_text}`;
    }

    // EM Bar & Marker
    const spot = currentSpotPrice;
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

    // 차트 토글 버튼 활성화 및 차트 그리기
    const toggle = $('gex-strike-toggle');
    if (g.by_strike && g.by_strike.length) {
        if (toggle) toggle.classList.remove('hidden');
        if (gexStrikesExpanded) drawGexBarChart();
    }

    renderSpreadOptimizer(g.spread_optimizer);
}
