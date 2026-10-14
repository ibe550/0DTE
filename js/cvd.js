var currentCvdTf = '10m';
var currentCvdData = null;
var cvdBarsCache = [];

function safeSet(id, val) {
    var el = $(id);
    if (el && val !== undefined && val !== null) {
        el.innerText = val;
    }
}

// 1. 타임프레임 전환 (1m / 5m / 10m / 15m / 30m / 1H)
function setCvdTimeframe(tf) {
    if (currentCvdTf === tf) return;
    currentCvdTf = tf;
    
    var buttons = document.querySelectorAll('[data-cvd-tf]');
    buttons.forEach(function(btn) {
        if (btn.getAttribute('data-cvd-tf') === tf) {
            btn.className = 'px-2 py-0.5 text-xs font-mono font-bold bg-emerald-600 text-white rounded shadow-sm';
        } else {
            btn.className = 'px-2 py-0.5 text-xs font-mono font-semibold bg-slate-800 text-slate-400 hover:text-slate-200 rounded';
        }
    });

    if (typeof fetchRealMarketData === 'function') {
        fetchRealMarketData();
    }
}

// 2. 수치 포맷팅 헬퍼 (K / M 표기)
function fmtCvdVal(v, withSign) {
    if (v === null || v === undefined || isNaN(v)) return '--';
    var sign = '';
    if (v > 0 && withSign) sign = '+';
    var abs = Math.abs(v);
    if (abs >= 1000000) return sign + (v / 1000000).toFixed(1) + 'M';
    if (abs >= 1000) return sign + (v / 1000).toFixed(0) + 'K';
    return sign + Math.round(v);
}

// 3. 듀얼 Y축 캔버스 렌더링 엔진
function drawCvdChart() {
    var canvas = $('cvd-chart-canvas');
    if (!canvas) canvas = $('cvd-canvas');
    if (!canvas || !currentCvdData) return;

    // 모든 가능한 배열 구조(bars, series, data, candles, 또는 직접 배열) 자동 탐색
    var bars = [];
    if (Array.isArray(currentCvdData)) {
        bars = currentCvdData;
    } else if (currentCvdData) {
        bars = currentCvdData.bars || currentCvdData.series || currentCvdData.data || currentCvdData.candles || currentCvdData.history || [];
    }
    if (!Array.isArray(bars) || bars.length === 0) return;

    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    var w = rect.width;
    var h = rect.height;

    var padLeft = 58;  // 좌측 CVD Y축 여백
    var padRight = 52; // 우측 Volume Y축 여백
    var padTop = 26;
    var padBottom = 26;

    var chartW = w - padLeft - padRight;
    var chartH = h - padTop - padBottom;

    ctx.clearRect(0, 0, w, h);

    var maxVol = 100;
    var minCvd = Infinity;
    var maxCvd = -Infinity;

    bars.forEach(function(b) {
        var vol = Number(b.volume || b.vol || 0);
        if (vol > maxVol) maxVol = vol;

        var cvdVal = Number(b.cvd !== undefined ? b.cvd : (b.cum_delta !== undefined ? b.cum_delta : 0));
        if (cvdVal > maxCvd) maxCvd = cvdVal;
        if (cvdVal < minCvd) minCvd = cvdVal;
    });

    var absMaxCvd = Math.max(Math.abs(maxCvd), Math.abs(minCvd), 1000);
    var cvdScaleMax = Math.ceil((absMaxCvd * 1.15) / 1000) * 1000;
    var volScaleMax = Math.ceil((maxVol * 1.2) / 1000) * 1000;

    var midY = padTop + chartH / 2;

    // 가로 점선 보조 그리드 및 듀얼 Y축 눈금 출력
    var levels = [
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

    // 막대 거래량 및 CVD 선 렌더링
    var stepX = chartW / bars.length;
    var barW = Math.max(4, Math.min(24, stepX * 0.65));
    cvdBarsCache = [];
    var cvdPoints = [];

    bars.forEach(function(b, i) {
        var x = padLeft + (i + 0.5) * stepX;
        var vol = Number(b.volume || b.vol || 0);
        var delta = Number(b.delta !== undefined ? b.delta : ((b.buy_vol || 0) - (b.sell_vol || 0)));
        var cvdVal = Number(b.cvd !== undefined ? b.cvd : (b.cum_delta !== undefined ? b.cum_delta : 0));

        var volH = (vol / volScaleMax) * (chartH * 0.45);
        var barY = (padTop + chartH) - volH;

        ctx.fillStyle = delta >= 0 ? 'rgba(16, 185, 129, 0.45)' : 'rgba(244, 63, 94, 0.45)';
        ctx.beginPath();
        if (ctx.roundRect) {
            ctx.roundRect(x - barW / 2, barY, barW, volH, [2, 2, 0, 0]);
        } else {
            ctx.rect(x - barW / 2, barY, barW, volH);
        }
        ctx.fill();

        var cvdY = midY - (cvdVal / cvdScaleMax) * (chartH / 2);
        cvdPoints.push({ x: x, y: cvdY, bar: b, vol: vol, delta: delta, cvdVal: cvdVal });

        if (i % Math.ceil(bars.length / 6) === 0 || i === bars.length - 1) {
            ctx.fillStyle = '#64748b';
            ctx.font = '10px monospace';
            ctx.textAlign = 'center';
            var timeStr = b.time || b.timestamp || '';
            var shortTime = timeStr.indexOf(' ') !== -1 ? timeStr.split(' ')[1].slice(0, 5) : timeStr.slice(0, 5);
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

        var lastPt = cvdPoints[cvdPoints.length - 1];
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

// 4. 인터랙티브 툴팁
function initCvdInteraction() {
    var canvas = $('cvd-chart-canvas');
    if (!canvas) canvas = $('cvd-canvas');
    var tt = $('cvd-tooltip');
    if (!tt) tt = $('cvd-chart-tooltip');
    if (!canvas) return;

    function handleMove(clientX, clientY) {
        if (!cvdBarsCache.length) return;
        var rect = canvas.getBoundingClientRect();
        var mouseX = clientX - rect.left;
        var mouseY = clientY - rect.top;

        var closest = null;
        var minDiff = Infinity;
        cvdBarsCache.forEach(function(pt) {
            var diff = Math.abs(pt.x - mouseX);
            if (diff < minDiff) {
                minDiff = diff;
                closest = pt;
            }
        });

        if (closest && minDiff < 30 && tt) {
            tt.classList.remove('hidden');
            var timeStr = closest.bar.time || closest.bar.timestamp || '--';
            safeSet('cvd-tt-time', timeStr);
            safeSet('cvd-tt-vol', Number(closest.vol).toLocaleString());
            
            var deltaEl = $('cvd-tt-delta');
            if (deltaEl) {
                deltaEl.innerText = fmtCvdVal(closest.delta, true);
                deltaEl.className = 'font-bold ' + (closest.delta >= 0 ? 'text-emerald-400' : 'text-rose-400');
            }

            var cvdEl = $('cvd-tt-cvd');
            if (cvdEl) {
                cvdEl.innerText = fmtCvdVal(closest.cvdVal, true);
                cvdEl.className = 'font-bold ' + (closest.cvdVal >= 0 ? 'text-emerald-400' : 'text-rose-400');
            }

            var ttLeft = closest.x + 15;
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

// 5. 실시간 백엔드 데이터 수신 및 모든 텍스트 라벨 일괄 갱신
function renderCvd(cvd) {
    if (!cvd) return;
    currentCvdData = cvd;

    // 상단 메타데이터 바인딩
    var srcTxt = cvd.source || 'Charles Schwab (SPY)';
    if (typeof srcShort === 'function') srcTxt = srcShort(srcTxt);
    safeSet('cvd-source', srcTxt);
    safeSet('cvd-asof', cvd.as_of || cvd.timestamp || cvd.time || '--');

    // 배열 추출
    var bars = [];
    if (Array.isArray(cvd)) {
        bars = cvd;
    } else {
        bars = cvd.bars || cvd.series || cvd.data || cvd.candles || cvd.history || [];
    }

    if (bars && bars.length > 0) {
        var lastBar = bars[bars.length - 1];
        var firstBar = bars[0];

        // 집계 구간 및 데이터 건수
        var tStart = (firstBar.time || firstBar.timestamp || '').slice(-8, -3);
        var tEnd = (lastBar.time || lastBar.timestamp || '').slice(-8, -3);
        safeSet('cvd-period', (tStart && tEnd) ? (tStart + ' ~ ' + tEnd) : currentCvdTf.toUpperCase());
        safeSet('cvd-count', bars.length + '개 봉');

        // 마지막 봉 시간
        safeSet('cvd-last-bar', lastBar.time || lastBar.timestamp || '--');
        safeSet('cvd-last', lastBar.time || lastBar.timestamp || '--');

        // 최근 봉 델타 & 전체 누적 CVD
        var lastDelta = Number(lastBar.delta !== undefined ? lastBar.delta : ((lastBar.buy_vol || 0) - (lastBar.sell_vol || 0)));
        var lastCvd = Number(lastBar.cvd !== undefined ? lastBar.cvd : (lastBar.cum_delta || 0));
        safeSet('cvd-recent', fmtCvdVal(lastDelta, true));
        safeSet('cvd-total', fmtCvdVal(lastCvd, true));

        // 총 Buy / Sell 볼륨 집계
        var totalBuy = 0, totalSell = 0;
        bars.forEach(function(b) {
            totalBuy += Number(b.buy_vol || (b.delta > 0 ? b.volume : 0) || 0);
            totalSell += Number(b.sell_vol || (b.delta < 0 ? b.volume : 0) || 0);
        });
        safeSet('cvd-buy', fmtCvdVal(totalBuy, false));
        safeSet('cvd-sell', fmtCvdVal(totalSell, false));
        safeSet('cvd-buy-vol', fmtCvdVal(totalBuy, false));
        safeSet('cvd-sell-vol', fmtCvdVal(totalSell, false));

        // 상단 방향성 뱃지
        var badgeEl = $('cvd-badge') || $('cvd-status');
        if (badgeEl) {
            if (lastCvd > 0) {
                badgeEl.innerText = '매수 우세 (Bull)';
                badgeEl.className = 'text-xs font-bold px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-600';
            } else {
                badgeEl.innerText = '매도 우세 (Bear)';
                badgeEl.className = 'text-xs font-bold px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-600';
            }
        }
    }

    drawCvdChart();
}
