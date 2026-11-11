let currentGexData = null;
let currentSpotPrice = null;
let currentLevels = null;
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

    // 4. 지지/저항 레벨 수직선 (2026-11-10) — 야간 ES 고/저 + 전일 고/저/종가
    // 현물선과 같은 선형 보간 (minK~maxK 범위 안에 있는 레벨만 표시)
    // 라벨은 배경 pill + 행 교대로 그려서 겹침/막대 가림 방지 (2026-11-10 수정)
    if (currentLevels && strikes.length >= 2) {
        const minK = strikes[0].strike;
        const maxK = strikes[strikes.length - 1].strike;
        const levelDefs = [
            { key: 'overnight_high', label: '야간고', color: '#f59e0b', dash: [6, 3] },
            { key: 'overnight_low', label: '야간저', color: '#f59e0b', dash: [6, 3] },
            { key: 'prev_high', label: '전고', color: '#38bdf8', dash: [2, 3] },
            { key: 'prev_low', label: '전저', color: '#38bdf8', dash: [2, 3] },
            { key: 'prev_close', label: '전종', color: '#94a3b8', dash: [] },
        ];
        const labelSpots = [];
        levelDefs.forEach(ld => {
            const px = currentLevels[ld.key];
            if (typeof px !== 'number' || !isFinite(px)) return;
            if (px < minK || px > maxK) return;
            const lx = padX + ((px - minK) / (maxK - minK)) * (w - padX - 16);
            ctx.strokeStyle = ld.color;
            ctx.lineWidth = 1.5;
            ctx.setLineDash(ld.dash);
            ctx.beginPath();
            ctx.moveTo(lx, 30);
            ctx.lineTo(lx, h - padBottom);
            ctx.stroke();
            ctx.setLineDash([]);
            labelSpots.push({ x: lx, label: ld.label, color: ld.color });
        });
        // 라벨: x순 정렬 후 가까운 라벨은 아래 행으로 (배경 pill로 막대 위에서도 읽히게)
        labelSpots.sort((a, b) => a.x - b.x);
        ctx.font = 'bold 10px monospace';
        const lastX = [-Infinity, -Infinity];
        labelSpots.forEach(s => {
            const tw = ctx.measureText(s.label).width;
            let row = 0;
            if (s.x - lastX[0] < tw + 14) row = 1;
            if (row === 1 && s.x - lastX[1] < tw + 14) row = 0;
            const ly = 42 + row * 18;
            ctx.fillStyle = 'rgba(2, 6, 23, 0.88)';
            ctx.beginPath();
            ctx.roundRect(s.x - tw / 2 - 4, ly - 11, tw + 8, 14, 4);
            ctx.fill();
            ctx.fillStyle = s.color;
            ctx.textAlign = 'center';
            ctx.fillText(s.label, s.x, ly);
            lastX[row] = s.x;
        });
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

// 만기까지 카운트다운 (8) — ET 기준 당일 16:00, 마감 후/주말이면 다음 거래일
function expiryCountdownText() {
    try {
        const etNow = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
        const target = new Date(etNow);
        target.setHours(16, 0, 0, 0);
        if (etNow >= target || etNow.getDay() === 0 || etNow.getDay() === 6) {
            do { target.setDate(target.getDate() + 1); } while (target.getDay() === 0 || target.getDay() === 6);
        }
        const diffMs = target - etNow;
        if (diffMs <= 0) return '';
        const h = Math.floor(diffMs / 3600000), m = Math.floor((diffMs % 3600000) / 60000);
        const dayLbl = target.getDate() !== etNow.getDate() ? `(${(target.getMonth() + 1)}/${target.getDate()}) ` : '';
        return `⏳ 만기까지 ${dayLbl}${h}시간 ${m}분`;
    } catch (e) { return ''; }
}

function renderGex(g, _spot, levels) {
    const note = $('gex-note');
    if (!g || !g.available) {
        setText('gex-source', NA); setText('gex-meta', NA); setText('gex-em', NA);
        setText('gex-put-wall', NA); setText('gex-flip', NA); setText('gex-call-wall', NA);
        setText('gex-abs-pin', NA); setText('gex-max-pain', NA);
        const _sk = $('gex-oi-skew'); if (_sk) _sk.classList.add('hidden');
        if (note) { note.classList.remove('hidden'); note.innerText = (g && g.reason) || 'GEX 데이터를 불러올 수 없습니다.'; }
        // stale 방지: 이전 세션의 차트·마커·배너를 모두 초기화 (어제의 월을 오늘로 오판 방지)
        currentGexData = null;
        currentSpotPrice = null;
        currentLevels = null;
        chartBars = [];
        const _cv = $('gex-chart-canvas');
        if (_cv) { const _cx = _cv.getContext('2d'); if (_cx) _cx.clearRect(0, 0, _cv.width, _cv.height); }
        const _rg = $('gex-regime'); if (_rg) _rg.classList.add('hidden');
        const _em = $('em-range-bar'); if (_em) _em.style.width = '0%';
        ['marker-current', 'marker-put-line', 'marker-call-line', 'marker-flip-line'].forEach(id => {
            const _m = $(id); if (_m) _m.style.display = 'none';
        });
        return;
    }
    if (note) note.classList.add('hidden');
    currentGexData = g;
    currentSpotPrice = isNum(g.spot) ? g.spot : (isNum(g.gamma_flip) ? g.gamma_flip : null);
    currentLevels = (levels && typeof levels === 'object') ? levels : null;

    setText('gex-source', srcShort(g.source));
    const dte = (typeof g.dte_days === 'number') ? g.dte_days : (g.is_0dte ? 0 : 1);
    const dteLabel = dte <= 0 ? '0DTE 당일 만기' : (dte + 'DTE');
    setText('gex-meta', `${g.expiration || ''} (${dteLabel}) · 행사가 ${g.strike_count || 0}개 · ${expiryCountdownText()}` + (g.gamma_source_note ? ` · ${g.gamma_source_note}` : ''));
    setText('gex-em', g.expected_move || NA);
    // 월까지 거리 (현재가 대비 ±Npt) — 트레이더 암산 제거
    const wallDist = (w) => {
        if (!isNum(w) || !isNum(currentSpotPrice)) return '';
        const d = w - currentSpotPrice;
        return ` (${d >= 0 ? '+' : ''}${d.toFixed(1)}pt)`;
    };
    setText('gex-put-wall', isNum(g.put_wall) ? fmt(g.put_wall, 1) + wallDist(g.put_wall) : NA);
    setText('gex-flip', isNum(g.gamma_flip) ? fmt(g.gamma_flip, 1) + wallDist(g.gamma_flip) : NA);
    setText('gex-call-wall', isNum(g.call_wall) ? fmt(g.call_wall, 1) + wallDist(g.call_wall) : NA);

    const pinText = isNum(g.abs_pin_strike) ? `${fmt(g.abs_pin_strike, 0)} (${g.abs_pin_val}M$)` : NA;
    setText('gex-abs-pin', pinText);
    // Max Pain 표시 (10)
    setText('gex-max-pain', isNum(g.max_pain) ? fmt(g.max_pain, 1) + wallDist(g.max_pain) : NA);

    // OI Skew 미니바 (9) — 콜/풋 OI 쏠림으로 포지셔닝 편향 표시
    const skew = g.oi_skew;
    const skewBox = $('gex-oi-skew');
    if (skewBox && skew) {
        const cOI = (skew.call_oi_at_or_above_spot || 0) + (skew.call_oi_below_spot || 0);
        const pOI = (skew.put_oi_at_or_above_spot || 0) + (skew.put_oi_below_spot || 0);
        const tot = cOI + pOI;
        if (tot > 0) {
            skewBox.classList.remove('hidden');
            const cPct = Math.round(cOI / tot * 100), pPct = 100 - cPct;
            $('gex-oi-skew-callbar').style.width = cPct + '%';
            $('gex-oi-skew-putbar').style.width = pPct + '%';
            setText('gex-oi-skew-callpct', cPct + '%');
            setText('gex-oi-skew-putpct', pPct + '%');
            const bias = cPct >= 58 ? 'CALL 쏠림' : (pPct >= 58 ? 'PUT 쏠림' : '균형');
            const biasEl = $('gex-oi-skew-label');
            if (biasEl) { biasEl.innerText = bias; biasEl.style.color = cPct >= 58 ? '#6ee7b7' : (pPct >= 58 ? '#fda4af' : '#94a3b8'); }
        } else {
            skewBox.classList.add('hidden');
        }
    }

    // 풋/콜 비율 (2026-11-09) — 현물 ±12% 밴드 내 거래량/OI 기준, 1.0 초과면 풋 우세
    const pc = g.put_call;
    const pcBox = $('gex-put-call');
    if (pcBox && pc) {
        const vr = pc.vol_ratio, or = pc.oi_ratio;
        if (isNum(vr) || isNum(or)) {
            pcBox.classList.remove('hidden');
            setText('gex-pc-vol', isNum(vr) ? vr.toFixed(2) : NA);
            setText('gex-pc-oi', isNum(or) ? or.toFixed(2) : NA);
            const volEl = $('gex-pc-vol');
            if (volEl && isNum(vr)) volEl.style.color = vr >= 1.2 ? '#fda4af' : (vr <= 0.7 ? '#6ee7b7' : '#e2e8f0');
        } else {
            pcBox.classList.add('hidden');
        }
    }

    // 지지/저항 레벨 (2026-11-10) — 야간 ES 고/저 + 전일 고/저/종가 (현재가 대비 거리 표시)
    const lvBox = $('gex-levels');
    if (lvBox) {
        const lv = currentLevels;
        const hasLv = lv && lv.available && (isNum(lv.overnight_high) || isNum(lv.overnight_low) ||
            isNum(lv.prev_high) || isNum(lv.prev_low) || isNum(lv.prev_close));
        if (hasLv) {
            lvBox.classList.remove('hidden');
            const lvDist = (v) => {
                if (!isNum(v) || !isNum(currentSpotPrice)) return '';
                const d = v - currentSpotPrice;
                return ` (${d >= 0 ? '+' : ''}${d.toFixed(1)})`;
            };
            setText('lv-on-hi', isNum(lv.overnight_high) ? fmt(lv.overnight_high, 1) + lvDist(lv.overnight_high) : NA);
            setText('lv-on-lo', isNum(lv.overnight_low) ? fmt(lv.overnight_low, 1) + lvDist(lv.overnight_low) : NA);
            setText('lv-prev-hi', isNum(lv.prev_high) ? fmt(lv.prev_high, 1) + lvDist(lv.prev_high) : NA);
            setText('lv-prev-lo', isNum(lv.prev_low) ? fmt(lv.prev_low, 1) + lvDist(lv.prev_low) : NA);
            setText('lv-prev-cl', isNum(lv.prev_close) ? fmt(lv.prev_close, 1) + lvDist(lv.prev_close) : NA);
        } else {
            lvBox.classList.add('hidden');
        }
    }

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

}

// ─────────────────────────────────────────────────────────────

