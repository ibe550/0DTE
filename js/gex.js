let currentGexData = null;
let currentSpotPrice = null;
let chartBars = [];

// ─────────────────────────────────────────────────────────────
// 0DTE GEX 대칭 막대 그래프 렌더링 엔진
// ─────────────────────────────────────────────────────────────
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
    const padX = 64;
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

    // 1. 가로 그리드 점선 및 선명한 Y축 레이블
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

        ctx.font = 'bold 12px monospace';
        ctx.textAlign = 'right';
        if (gl.val > 0) {
            ctx.fillStyle = '#34d399';
            ctx.fillText(`+${gl.val}M`, padX - 14, gl.y + 4);
        } else if (gl.val < 0) {
            ctx.fillStyle = '#fb7185';
            ctx.fillText(`${gl.val}M`, padX - 14, gl.y + 4);
        } else {
            ctx.fillStyle = '#f8fafc';
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

        if (callBarH > 1) {
            ctx.fillStyle = '#10b981';
            ctx.beginPath();
            ctx.roundRect(x - barWidth / 2, midY - callBarH, barWidth, callBarH, [4, 4, 0, 0]);
            ctx.fill();
        }

        if (putBarH > 1) {
            ctx.fillStyle = '#f43f5e';
            ctx.beginPath();
            ctx.roundRect(x - barWidth / 2, midY, barWidth, putBarH, [0, 0, 4, 4]);
            ctx.fill();
        }

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

    // 3. 현재 지수 수직선 및 상단 배지
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
// 인터랙티브 툴팁 이벤트
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
// 0DTE CREDIT SPREAD OPTIMIZER
// ─────────────────────────────────────────────────────────────
function renderSpreadOptimizer(opt, gexData) {
    const card = $('spread-optimizer-card');
    if (!card) return;

    if (!opt || !opt.available) {
        if (gexData && gexData.available && currentSpotPrice) {
            const spot = currentSpotPrice;
            const em = isNum(gexData.em_pt) ? gexData.em_pt : 25.0;
            const cWall = isNum(gexData.call_wall) ? gexData.call_wall : (spot + em);
            const pWall = isNum(gexData.put_wall) ? gexData.put_wall : (spot - em);

            const now = new Date();
            const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
            const nowET = new Date(utc - (4 * 3600000));
            const currentMins = nowET.getHours() * 60 + nowET.getMinutes();
            const closeMins = 16 * 60;
            const remainMins = Math.max(10, Math.min(390, closeMins - currentMins));
            const timeDecayFactor = Math.sqrt(remainMins / 390);

            // Bear Call Spread
            const callBound = Math.max(cWall, spot + em);
            const callShort = Math.ceil((callBound + 5) / 5) * 5;
            const callLong = callShort + 10;
            const callDist = callShort - spot;
            
            let rawCallCredit = Math.max(0.05, (3.2 / (1 + (callDist / 12) * 1.8)) * timeDecayFactor);
            rawCallCredit = Math.round(rawCallCredit * 20) / 20;

            let callStatus = 'WAITING';
            let callBadge = '⏳ 대기';
            let callGuide = `상방 방어선 이격 +${(callShort - callBound).toFixed(1)}pt`;

            if (callDist < 10) {
                callStatus = 'DANGER';
                callBadge = '⛔ 진입 금지 (근접 위험)';
                callGuide = `현재가 근접(이격 ${callDist.toFixed(1)}pt) · 감마 스퀴즈 위험`;
            } else if (rawCallCredit >= 1.00 && rawCallCredit <= 1.40) {
                callStatus = 'SWEET_SPOT';
                callBadge = '✅ 진입 적격 (스윗스팟)';
                callGuide = `방어선 바깥 +${(callShort - callBound).toFixed(1)}pt · 안정적 진입`;
            } else {
                callStatus = 'SWEET_SPOT';
                callBadge = '✅ 진입 적격';
                callGuide = `방어선 바깥 +${(callShort - callBound).toFixed(1)}pt · 이격 확보 완료`;
            }

            // Bull Put Spread
            const putBound = Math.min(pWall, spot - em);
            const putShort = Math.floor((putBound - 5) / 5) * 5;
            const putLong = putShort - 10;
            const putDist = spot - putShort;

            let rawPutCredit = Math.max(0.05, (3.4 / (1 + (putDist / 12) * 1.8)) * timeDecayFactor);
            rawPutCredit = Math.round(rawPutCredit * 20) / 20;

            let putStatus = 'WAITING';
            let putBadge = '⏳ 대기';
            let putGuide = `하방 방어선 이격 -${(putBound - putShort).toFixed(1)}pt`;

            if (putDist < 10) {
                putStatus = 'DANGER';
                putBadge = '⛔ 진입 금지 (근접 위험)';
                putGuide = `현재가 근접(이격 ${putDist.toFixed(1)}pt) · 감마 스퀴즈 위험`;
            } else if (rawPutCredit >= 1.00 && rawPutCredit <= 1.40) {
                putStatus = 'SWEET_SPOT';
                putBadge = '✅ 진입 적격 (스윗스팟)';
                putGuide = `방어선 바깥 -${(putBound - putShort).toFixed(1)}pt · 안정적 진입`;
            } else {
                putStatus = 'SWEET_SPOT';
                putBadge = '✅ 진입 적격';
                callGuide = `방어선 바깥 -${(putBound - putShort).toFixed(1)}pt · 이격 확보 완료`;
            }

            opt = {
                available: true,
                width: 10,
                call_spread: {
                    short: callShort,
                    long: callLong,
                    credit: rawCallCredit,
                    boundary: callBound.toFixed(1),
                    status: callStatus,
                    badge: callBadge,
                    guide: callGuide
                },
                put_spread: {
                    short: putShort,
                    long: putLong,
                    credit: rawPutCredit,
                    boundary: putBound.toFixed(1),
                    status: putStatus,
                    badge: putBadge,
                    guide: putGuide
                }
            };
        } else {
            setText('opt-call-status', '대기');
            setText('opt-put-status', '대기');
            return;
        }
    }

    const c = opt.call_spread;
    if (c) {
        setText('opt-call-strikes', `Short ${c.short} / Long ${c.long}`);
        // '목록 크레딧' 문구 관련 요소가 있으면 숨김 처리
        const callCreditEl = $('opt-call-credit');
        if (callCreditEl && callCreditEl.parentElement) {
            callCreditEl.parentElement.style.display = 'none';
        }
        setText('opt-call-bound', `${c.boundary}`);
        // renderSpreadOptimizer 함수 내부 하단 수정 예시:
    const c = opt.call_spread;
    if (c) {
        setText('opt-call-strikes', `Short ${c.short} / Long ${c.long}`);
        setText('opt-call-bound', `${c.boundary}`);
        
        // ── N/A가 뜨던 하단 가이드 칸을 아예 비우거나 숨김 ──
        const callGuideEl = $('opt-call-guide');
        if (callGuideEl) {
            callGuideEl.textContent = '';
            if (callGuideEl.parentElement) callGuideEl.parentElement.style.display = 'none';
        }

        const stEl = $('opt-call-status');
        if (stEl) {
            stEl.innerText = c.badge || '대기';
            stEl.className = `text-xs font-bold px-2.5 py-1 rounded-md border ${c.status === 'SWEET_SPOT' ? 'bg-emerald-950 text-emerald-300 border-emerald-500' : (c.status === 'WAITING' ? 'bg-slate-800 text-indigo-300 border-indigo-500' : 'bg-rose-950 text-rose-300 border-rose-500')}`;
        }
    }

    const p = opt.put_spread;
    if (p) {
        setText('opt-put-strikes', `Short ${p.short} / Long ${p.long}`);
        setText('opt-put-bound', `${p.boundary}`);
        
        // ── N/A가 뜨던 하단 가이드 칸을 아예 비우거나 숨김 ──
        const putGuideEl = $('opt-put-guide');
        if (putGuideEl) {
            putGuideEl.textContent = '';
            if (putGuideEl.parentElement) putGuideEl.parentElement.style.display = 'none';
        }

        const stEl = $('opt-put-status');
        if (stEl) {
            stEl.innerText = p.badge || '대기';
            stEl.className = `text-xs font-bold px-2.5 py-1 rounded-md border ${p.status === 'SWEET_SPOT' ? 'bg-emerald-950 text-emerald-300 border-emerald-500' : (p.status === 'WAITING' ? 'bg-slate-800 text-indigo-300 border-indigo-500' : 'bg-rose-950 text-rose-300 border-rose-500')}`;
        }
    }

function renderGex(g) {
    const note = $('gex-note');
    if (!g || !g.available) {
        setText('gex-source', NA); setText('gex-meta', NA); setText('gex-em', NA);
        setText('gex-put-wall', NA); setText('gex-flip', NA); setText('gex-call-wall', NA);
        setText('gex-abs-pin', NA);
        if (note) { note.classList.remove('hidden'); note.innerText = (g && g.reason) || 'GEX 데이터를 불러올 수 없습니다.'; }
        renderSpreadOptimizer(null, null);
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

    // 상시 노출 렌더링
    if (g.by_strike && g.by_strike.length) {
        drawGexBarChart();
    }

    // 옵티마이저 바인딩 (fallback 파라미터 전달)
    renderSpreadOptimizer(g.spread_optimizer, g);
}
