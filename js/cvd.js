let currentCvdTf = '10m';
let currentCvdData = null;
let cvdBarsCache = [];

// 1. Timeframe switch (1m / 5m / 10m / 30m)
function setCvdTimeframe(tf) {
    if (currentCvdTf === tf) return;
    currentCvdTf = tf;
    
    const buttons = document.querySelectorAll('[data-cvd-tf]');
    buttons.forEach(function(btn) {
        if (btn.getAttribute('data-cvd-tf') === tf) {
            btn.className = 'px-2 py-0.5 text-xs font-mono font-bold bg-indigo-600 text-white rounded shadow-sm';
        } else {
            btn.className = 'px-2 py-0.5 text-xs font-mono font-semibold bg-slate-800 text-slate-400 hover:text-slate-200 rounded';
        }
    });

    if (typeof fetchRealMarketData === 'function') {
        fetchRealMarketData();
    }
}

// 2. Value formatting helper (K / M)
function fmtCvdVal(v, withSign) {
    if (v === null || v === undefined || isNaN(v)) return '--';
    const sign = (v > 0 && withSign) ? '+' : '';
    const abs = Math.abs(v);
    if (abs >= 1000000) return sign + (v / 1000000).toFixed(1) + 'M';
    if (abs >= 1000) return sign + (v / 1000).toFixed(0) + 'K';
    return sign + Math.round(v);
}

// 3. CVD Chart renderer with dual Y-axis
function drawCvdChart() {
    const canvas = $('cvd-chart-canvas') || $('cvd-canvas');
    if (!canvas || !currentCvdData) return;

    const bars = currentCvdData.bars || currentCvdData.series || currentCvdData.data || [];
    if (!Array.isArray(bars) || bars.length === 0) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;

    const padLeft = 58;
    const padRight = 52;
    const padTop = 26;
    const padBottom = 26;

    const chartW = w - padLeft - padRight;
    const chartH = h - padTop - padBottom;

    ctx.clearRect(0, 0, w, h);

    let maxVol = 100;
    let minCvd = Infinity;
    let maxCvd = -Infinity;

    bars.forEach(function(b) {
        const vol = Number(b.volume || b.vol || 0);
        if (vol > maxVol) maxVol = vol;

        const cvdVal = Number(b.cvd !== undefined ? b.cvd : (b.cum_delta || 0));
        if (cvdVal > maxCvd) maxCvd = cvdVal;
        if (cvdVal < minCvd) minCvd = cvdVal;
    });

    const absMaxCvd = Math.max(Math.abs(maxCvd), Math.abs(minCvd), 1000);
    const cvdScaleMax = Math.ceil((absMaxCvd * 1.15) / 1000) * 1000;
    const volScaleMax = Math.ceil((maxVol * 1.2) / 1000) * 1000;

    const midY = padTop + chartH / 2;

    const levels = [
        { cvd: cvdScaleMax,       vol: volScaleMax,        y: padTop },
        { cvd: cvdScaleMax / 2,   vol: volScaleMax * 0.75, y: padTop + chartH * 0.25 },
        { cvd: 0,                 vol: volScaleMax * 0.5,  y: midY },
        { cvd: -cvdScaleMax / 2,  vol: volScaleMax * 0.25, y: padTop + chartH * 0.75 },
        { cvd: -cvdScaleMax,      vol: 0,                  y: padTop + chartH }
    ];

    levels.forEach(function(lvl) {
        ctx.strokeStyle = lvl.cvd === 0 ? 'rgba(148, 163, 184, 0.7)' : 'rgba(51, 65, 85, 0.4)';
        ctx.lineWidth = lvl.cvd === 0 ? 1.5 : 1;
        ctx.setLineDash(lvl.cvd === 0 ? [] : [3, 3]);
        ctx.beginPath();
        ctx.moveTo(padLeft - 6, lvl.y);
        ctx.lineTo(w - padRight + 6, lvl.y);
        ctx.stroke();

        ctx.font = 'bold 11px monospace';
        ctx.textAlign = 'right';
        if (lvl.cvd > 0) {
            ctx.fillStyle = '#34d399';
            ctx.fillText(fmtCvdVal(lvl.cvd, true), padLeft - 10, lvl.y + 3.5);
        } else if (lvl.cvd < 0) {
            ctx.fillStyle = '#fb7185';
            ctx.fillText(fmtCvdVal(lvl.cvd, true), padLeft - 10, lvl.y + 3.5);
        } else {
            ctx.fillStyle = '#f8fafc';
            ctx.fillText('0', padLeft - 10, lvl.y + 3.5);
        }

        ctx.textAlign = 'left';
        ctx.fillStyle = '#94a3b8';
        ctx.fillText(fmtCvdVal(lvl.vol, false), w - padRight + 10, lvl.y + 3.5);
    });
    ctx.setLineDash([]);

    ctx.font = 'bold 10px monospace';
    ctx.fillStyle = '#818cf8';
    ctx.textAlign = 'right';
    ctx.fillText('CVD(Delta)', padLeft - 10, padTop - 10);

    ctx.fillStyle = '#cbd5e1';
    ctx.textAlign = 'left';
    ctx.fillText('VOL', w - padRight + 10, padTop - 10);

    const stepX = chartW / bars.length;
    const barW = Math.max(4, Math.min(24, stepX * 0.65));
    cvdBarsCache = [];
    const cvdPoints = [];

    bars.forEach(function(b, i) {
        const x = padLeft + (i + 0.5) * stepX;
        const vol = Number(b.volume || b.vol || 0);
        const delta = Number(b.delta || (b.buy_vol - b.sell_vol) || 0);
        const cvdVal = Number(b.cvd !== undefined ? b.cvd : (b.cum_delta || 0));

        const volH = (vol / volScaleMax) * (chartH * 0.45);
        const barY = (padTop + chartH) - volH;

        ctx.fillStyle = delta >= 0 ? 'rgba(16, 185, 129, 0.45)' : 'rgba(244, 63, 94, 0.45)';
        ctx.beginPath();
        if (ctx.roundRect) {
            ctx.roundRect(x - barW / 2, barY, barW, volH, [2, 2, 0, 0]);
        } else {
            ctx.rect(x - barW / 2, barY, barW, volH);
        }
        ctx.fill();

        const cvdY = midY - (cvdVal / cvdScaleMax) * (chartH / 2);
        cvdPoints.push({ x: x, y: cvdY, bar: b, vol: vol, delta: delta, cvdVal: cvdVal });

        if (i % Math.ceil(bars.length / 6) === 0 || i === bars.length - 1) {
            ctx.fillStyle = '#64748b';
            ctx.font = '10px monospace';
            ctx.textAlign = 'center';
            const timeStr = b.time || b.timestamp || '';
            const shortTime = timeStr.includes(' ') ? timeStr.split(' ')[1].slice(0, 5) : timeStr.slice(0, 5);
            ctx.fillText(shortTime, x, h - 8);
        }
    });

    if (cvdPoints.length > 1) {
        ctx.strokeStyle = '#6366f1';
        ctx.lineWidth = 2.2;
        ctx.beginPath();
        cvdPoints.forEach(function(pt, idx) {
            if (idx === 0) ctx.moveTo(pt.x, pt.y);
            else ctx.lineTo(pt.x, pt.y);
        });
        ctx.stroke();

        const lastPt = cvdPoints[cvdPoints.length - 1];
        ctx.fillStyle = lastPt.cvdVal >= 0 ? '#10b981' : '#f43f5e';
        ctx.beginPath();
        ctx.arc(lastPt.x, lastPt.y, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1.5;
        ctx.stroke();
    }

    cvdBarsCache = cvdPoints;
}

// 4. Mouse and touch interaction
function initCvdInteraction() {
    const canvas = $('cvd-chart-canvas') || $('cvd-canvas');
    const tt = $('cvd-tooltip') || $('cvd-chart-tooltip');
    if (!canvas) return;

    function handleMove(clientX, clientY) {
        if (!cvdBarsCache.length) return;
        const rect = canvas.getBoundingClientRect();
        const mouseX = clientX - rect.left;
        const mouseY = clientY - rect.top;

        let closest = null;
        let minDiff = Infinity;
        cvdBarsCache.forEach(function(pt) {
            const diff = Math.abs(pt.x - mouseX);
            if (diff < minDiff) {
                minDiff = diff;
                closest = pt;
            }
        });

        if (closest && minDiff < 30 && tt) {
            tt.classList.remove('hidden');
            const timeStr = closest.bar.time || closest.bar.timestamp || '--';
            setText('cvd-tt-time', timeStr);
            setText('cvd-tt-vol', Number(closest.vol).toLocaleString());
            
            const deltaEl = $('cvd-tt-delta');
            if (deltaEl) {
                deltaEl.innerText = fmtCvdVal(closest.delta, true);
                deltaEl.className = 'font-bold ' + (closest.delta >= 0 ? 'text-emerald-400' : 'text-rose-400');
            }

            const cvdEl = $('cvd-tt-cvd');
            if (cvdEl) {
                cvdEl.innerText = fmtCvdVal(closest.cvdVal, true);
                cvdEl.className = 'font-bold ' + (closest.cvdVal >= 0 ? 'text-emerald-400' : 'text-rose-400');
            }

            let ttLeft = closest.x + 15;
            if (ttLeft + 160 > rect.width) ttLeft = closest.x - 170;
            tt.style.left = Math.max(10, ttLeft) + 'px';
            tt.style.top = Math.max(10, mouseY - 50) + 'px';
        } else if (tt) {
            tt.classList.add('hidden');
        }
    }

    canvas.addEventListener('mousemove', function(e) { handleMove(e.clientX, e.clientY); });
    canvas.addEventListener('mouseleave', function() { if (tt) tt.classList.add('hidden'); });
    canvas.addEventListener('touchmove', function(e) {
        if (e.touches.length > 0) handleMove(e.touches[0].clientX, e.touches[0].clientY);
    }, { passive: true });
    canvas.addEventListener('touchend', function() { if (tt) tt.classList.add('hidden'); });
    window.addEventListener('resize', drawCvdChart);
}

document.addEventListener('DOMContentLoaded', initCvdInteraction);

// 5. Render entry point
function renderCvd(cvd) {
    if (!cvd) return;
    currentCvdData = cvd;
    drawCvdChart();
}
