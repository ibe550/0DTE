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
// 0DTE GEX 대칭 막대 그래프 렌더링 엔진 (초고해상도 & 가독성 강화)
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
    const padTop = 38;
    const padBottom = 40;
    const padX = 64; // Y축 수치가 여유 있게 들어가도록 좌측 여백 확장
    const drawH = h - padTop - padBottom;
    const midY = padTop + drawH / 2;

    const strikes = [...currentGexData.by_strike].sort((a, b) => a.strike - b.strike);
    
    let maxVal = 10;
    strikes.forEach(s => {
        const cGex = s.call_gex_m ?? Math.max(0, (s.net_gex_m || 0));
        const pGex = s.put_gex_m ?? Math.abs(Math.min(0, (s.net_gex_m || 0)));
        if (cGex > maxVal) maxVal = cGex;
        if (pGex > maxVal) maxVal = pGex;
    });
    maxVal = Math.ceil((maxVal * 1.15) / 100) * 100;

    ctx.clearRect(0, 0, w, h);

    // 1. 가로 그리드 점선 및 선명한 Y축 레이블 (+1100M, 0, -1100M)
    const gridLevels = [
        { val: maxVal, y: padTop },
        { val: maxVal / 2, y: padTop + drawH * 0.25 },
        { val: 0, y: midY },
        { val: -maxVal / 2, y: padTop + drawH * 0.75 },
        { val: -maxVal, y: h - padBottom }
    ];

    gridLevels.forEach(gl => {
        ctx.strokeStyle = gl.val === 0 ? 'rgba(148, 163, 184, 0.9)' : 'rgba(51, 65, 85, 0.45)';
        ctx.lineWidth = gl.val === 0 ? 1.5 : 1;
        ctx.setLineDash(gl.val === 0 ? [] : [4, 4]);
        ctx.beginPath();
        ctx.moveTo(padX - 10, gl.y);
        ctx.lineTo(w - 16, gl.y);
        ctx.stroke();

        // 좌측 Y축 텍스트 (bold 12px 고대비 폰트)
        ctx.font = 'bold 12px monospace';
        ctx.textAlign = 'right';
        if (gl.val > 0) {
            ctx.fillStyle = '#34d399'; // 밝은 에메랄드
            ctx.fillText(`+${gl.val}M`, padX - 14, gl.y + 4);
        } else if (gl.val < 0) {
            ctx.fillStyle = '#fb7185'; // 밝은 로즈
            ctx.fillText(`${gl.val}M`, padX - 14, gl.y + 4);
        } else {
            ctx.fillStyle = '#f8fafc'; // 깨끗한 화이트
            ctx.fillText('0', padX - 14, gl.y + 4);
        }
    });
    ctx.setLineDash([]);

    // 2. 동적 막대 너비 렌더링
    const stepX = (w - padX - 16) / strikes.length;
    const barWidth = Math.max(16, Math.min(48, stepX * 0.65));
    chartBars = [];

    strikes.forEach((s, idx) => {
        const x = padX + (idx + 0.5) * stepX;
        const cGex = s.call_gex_m ?? Math.max(0, ((s.abs_gex_m + s.net_gex_m) / 2) || 0);
        const pGex = s.put_gex_m ?? Math.max(0, ((s.abs_gex_m - s.net_gex_m) / 2) || 0);

        const callBarH = (cGex / maxVal) * (drawH / 2);
        const putBarH = (pGex / maxVal) * (drawH / 2);

        // Call GEX 상방 막대
        if (callBarH > 1) {
            ctx.fillStyle = '#10b981';
            ctx.beginPath();
            ctx.roundRect(x - barWidth / 2, midY - callBarH, barWidth, callBarH, [4, 4, 0, 0]);
            ctx.fill();
        }

        // Put GEX 하방 막대
        if (putBarH > 1) {
            ctx.fillStyle = '#f43f5e';
            ctx.beginPath();
            ctx.roundRect(x - barWidth / 2, midY, barWidth, putBarH, [0, 0, 4, 4]);
            ctx.fill();
        }

        // X축 행사가 라벨 (12px 볼드)
        const isPin = currentGexData.abs_pin_strike && Math.abs(currentGexData.abs_pin_strike - s.strike) < 2;
        ctx.font = isPin ? 'bold 13px monospace' : 'bold 12px monospace';
        ctx.textAlign = 'center';

        if (isPin) {
            ctx.fillStyle = '#312e81';
            ctx.strokeStyle = '#818cf8';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.roundRect(x - 22, h - padBottom + 6, 44, 20, 5);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = '#e0e7ff';
            ctx.fillText(s.strike.toString(), x, h - padBottom + 20);
        } else {
            ctx.fillStyle = '#f1f5f9';
            ctx.fillText(s.strike.toString(), x, h - padBottom + 19);
        }

        ctx.strokeStyle = 'rgba(148, 163, 184, 0.6)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, h - padBottom);
        ctx.lineTo(x, h - padBottom + 5);
        ctx.stroke();

        chartBars.push({ x, barWidth, strikeData: s, cGex, pGex });
    });

    // 3. 현재 지수(SPX Spot) 수직선 및 상단 배지
    if (currentSpotPrice && strikes.length >= 2) {
        const minK = strikes[0].strike;
        const maxK = strikes[strikes.length - 1].strike;
        if (currentSpotPrice >= minK && currentSpotPrice <= maxK) {
            const spotPct = (currentSpotPrice - minK) / (maxK - minK);
            const spotX = padX + spotPct * (w - padX - 16);

            ctx.strokeStyle = '#818cf8';
            ctx.lineWidth = 1.5;
            ctx.setLineDash([4, 3]);
            ctx.beginPath();
            ctx.moveTo(spotX, 6);
            ctx.lineTo(spotX, h - padBottom);
            ctx.stroke();
            ctx.setLineDash([]);

            const badgeTxt = currentSpotPrice.toFixed(2);
            ctx.font = 'bold 12px monospace';
            const txtW = ctx.measureText(badgeTxt).width + 12;
            ctx.fillStyle = '#312e81';
            ctx.strokeStyle = '#a5b4fc';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.roundRect(spotX - txtW / 2, 6, txtW, 20, 4);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = '#ffffff';
            ctx.textAlign = 'center';
            ctx.fillText(badgeTxt, spotX, 20);
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

        let closest = null;
        let minDiff = Infinity;
        chartBars.forEach(b => {
            const diff = Math.abs(b.x - mouseX);
            if (diff < minDiff) {
                minDiff = diff;
                closest = b;
            }
        });

        if (closest && minDiff < 36) {
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

            tt.classList.remove('hidden');
            let ttLeft = closest.x + 16;
            if (ttLeft + 190 > rect.width) ttLeft = closest.x - 200;
            let ttTop = Math.max(10, mouseY - 70);
            if (ttTop + 190 > rect.height) ttTop = rect.height - 195;

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
// GEX 데이터 수신 및 옵티마이저 바인딩
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
            stEl.className = `text-xs font-bold px-2.5 py-1 rounded-md border ${c.status === 'SWEET_SPOT' ? 'bg-emerald-950 text-emerald-300 border-emerald-500' : (c.status === 'LOW_PREMIUM' ? 'bg-slate-800 text-slate-300 border-slate-600' : (c.status === 'WAITING' ? 'bg-slate-800 text-indigo-300 border-indigo-500' : 'bg-amber-950 text-amber-300 border-amber-500'))}`;
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
            stEl.className = `text-xs font-bold px-2.5 py-1 rounded-md border ${p.status === 'SWEET_SPOT' ? 'bg-emerald-950 text-emerald-300 border-emerald-500' : (p.status === 'LOW_PREMIUM' ? 'bg-slate-800 text-slate-300 border-slate-600' : (p.status === 'WAITING' ? 'bg-slate-800 text-indigo-300 border-indigo-500' : 'bg-amber-950 text-amber-300 border-amber-500'))}`;
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

    const toggle = $('gex-strike-toggle');
    if (g.by_strike && g.by_strike.length) {
        if (toggle) toggle.classList.remove('hidden');
        if (gexStrikesExpanded) drawGexBarChart();
    }

    renderSpreadOptimizer(g.spread_optimizer);
}
