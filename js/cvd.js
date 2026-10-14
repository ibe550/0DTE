var currentCvdTf = '10m';
var currentCvdData = null;
var cvdBarsCache = [];

function safeSet(id, val) {
    var el = document.getElementById(id);
    if (el && val !== undefined && val !== null) {
        el.textContent = val;
    }
}

function fmtCvdVal(v, withSign) {
    if (v === null || v === undefined || isNaN(v)) return '--';
    var sign = '';
    if (v > 0 && withSign) sign = '+';
    var abs = Math.abs(v);
    if (abs >= 1000000) return sign + (v / 1000000).toFixed(1) + 'M';
    if (abs >= 1000) return sign + (v / 1000).toFixed(1) + 'K';
    return sign + Math.round(v);
}

function formatEtTime(unixSec) {
    if (!unixSec) return '--';
    var d = new Date(unixSec * 1000);
    var utc = d.getTime() + (d.getTimezoneOffset() * 60000);
    var et = new Date(utc - (4 * 3600000)); // EDT (UTC-4)
    var hh = String(et.getHours()).padStart(2, '0');
    var mm = String(et.getMinutes()).padStart(2, '0');
    return hh + ':' + mm;
}

// 1. 타임프레임 전환 함수 (HTML onclick="changeCvdTimeframe(...)" 연동)
function changeCvdTimeframe(tf) {
    if (!tf) return;
    currentCvdTf = tf;
    
    var btns = document.querySelectorAll('#cvd-tf-group button, [data-cvd-tf]');
    btns.forEach(function(btn) {
        var bText = (btn.getAttribute('data-cvd-tf') || btn.innerText || '').trim().toLowerCase();
        if (bText === tf.toLowerCase()) {
            btn.className = 'px-2 py-0.5 text-xs font-mono font-bold bg-emerald-600 text-white rounded shadow-sm';
        } else {
            btn.className = 'px-2 py-0.5 text-xs font-mono font-semibold bg-slate-800 text-slate-400 hover:text-slate-200 rounded';
        }
    });

    if (typeof fetchRealMarketData === 'function') {
        fetchRealMarketData();
    }
}
window.changeCvdTimeframe = changeCvdTimeframe;
window.setCvdTimeframe = changeCvdTimeframe;

// 2. CVD 및 거래량 SVG 렌더링 진입점
function renderCvd(cvd) {
    if (!cvd) return;
    if (cvd.cvd && !cvd.bars) {
        cvd = cvd.cvd;
    }
    currentCvdData = cvd;

    var bars = cvd.bars || cvd.series || cvd.data || cvd.candles || [];
    if (!Array.isArray(bars) || bars.length === 0) return;

    // 상단 타이틀 & 메타데이터
    safeSet('cvd-title-tf', (currentCvdTf || '10M').toUpperCase());
    safeSet('cvd-source', cvd.source || 'Charles Schwab (SPY 10m)');
    
    var dtEl = document.getElementById('cvd-data-time');
    if (dtEl) {
        var dt = cvd.data_time || cvd.timestamp || cvd.time || '--';
        dtEl.innerText = dtEl.innerText.indexOf('Data as of') !== -1 ? ('Data as of ' + dt) : dt;
    }

    var priorBadge = document.getElementById('cvd-prior-badge');
    if (priorBadge) {
        if (cvd.is_prior) priorBadge.classList.remove('hidden');
        else priorBadge.classList.add('hidden');
    }

    // 봉 데이터 집계
    var maxVol = 10;
    var totalBuy = 0;
    var totalSell = 0;
    var cvdVals = [];

    bars.forEach(function(b) {
        var v = Number(b.vol !== undefined ? b.vol : (b.volume || 0));
        if (v > maxVol) maxVol = v;
        if (b.is_bull) totalBuy += v;
        else totalSell += v;
        var cLine = Number(b.cvd_line !== undefined ? b.cvd_line : (b.cvd || 0));
        cvdVals.push(cLine);
    });

    var totalVol = totalBuy + totalSell;
    var buyPct = totalVol > 0 ? ((totalBuy / totalVol) * 100).toFixed(1) : '50.0';
    var sellPct = totalVol > 0 ? ((totalSell / totalVol) * 100).toFixed(1) : '50.0';

    var firstBar = bars[0];
    var lastBar = bars[bars.length - 1];
    var lastCvd = cvdVals.length ? cvdVals[cvdVals.length - 1] : 0;

    var tStart = formatEtTime(firstBar.t);
    var tEnd = formatEtTime(lastBar.t);
    
    var rangeEl = document.getElementById('cvd-agg-range');
    if (rangeEl) {
        rangeEl.innerText = rangeEl.innerText.indexOf('집계 구간') !== -1 ? ('집계 구간 ' + tStart + ' ~ ' + tEnd + ' ET') : (tStart + ' ~ ' + tEnd + ' ET');
    }

    var descEl = document.getElementById('cvd-data-desc');
    if (descEl) {
        descEl.innerText = descEl.innerText.indexOf('데이터') !== -1 ? ('데이터 ' + bars.length + '개 봉') : (bars.length + '개 봉');
    }

    var pill = document.getElementById('cvd-status-pill');
    if (pill) {
        var isBull = totalBuy >= totalSell;
        pill.innerText = isBull ? '매수 우세 (Bull)' : '매도 우세 (Bear)';
        pill.className = isBull
            ? 'text-xs font-bold px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-600'
            : 'text-xs font-bold px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-600';
    }

    // Y축 눈금 수치 반영 (상단 점선 및 중간 점선)
    safeSet('cvd-y-max', fmtCvdVal(maxVol, false));
    safeSet('cvd-y-mid', fmtCvdVal(maxVol / 2, false));

    // 하단 상세 수치 반영
    safeSet('cvd-last-time', tEnd + ' ET');
    safeSet('cvd-recent-vol', fmtCvdVal(lastBar.vol, false));
    safeSet('cvd-total-vol', fmtCvdVal(totalVol, false));
    safeSet('cvd-buy-pct', '▲ Buy ' + buyPct + '%');
    safeSet('cvd-sell-pct', '▼ Sell ' + sellPct + '%');

    var barFill = document.getElementById('cvd-bar-fill');
    if (barFill) barFill.style.width = buyPct + '%';
    var sellFill = document.getElementById('cvd-sell-fill');
    if (sellFill) sellFill.style.width = sellPct + '%';

    safeSet('cvd-summary-text', 'SPY ' + (currentCvdTf || '10M').toUpperCase() + ' 누적: 총 거래량 ' + fmtCvdVal(totalVol, false) + ' (매수 ' + buyPct + '% / 매도 ' + sellPct + '%) · CVD ' + (lastCvd >= 0 ? '+' : '') + fmtCvdVal(lastCvd, false));

    // 3. SVG 차트 드로잉 (Volume 막대 및 CVD 꺾은선)
    var svg = document.getElementById('cvd-bars-svg');
    if (!svg) return;

    var w = 1000, h = 200;
    var vb = svg.getAttribute('viewBox');
    if (vb) {
        var parts = vb.trim().split(/[ ,]+/);
        if (parts.length === 4) {
            w = parseFloat(parts[2]) || 1000;
            h = parseFloat(parts[3]) || 200;
        }
    } else {
        svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
        svg.setAttribute('preserveAspectRatio', 'none');
    }

    var yTop = h * 0.16;
    var yZero = h * 0.82;
    var chartH = yZero - yTop;
    var stepX = w / bars.length;
    var barW = Math.max(3, Math.min(22, stepX * 0.68));

    // 볼륨 막대 (<g id="cvd-real-bars">)
    var realBarsGroup = document.getElementById('cvd-real-bars');
    if (realBarsGroup) {
        var barsHtml = '';
        bars.forEach(function(b, i) {
            var v = Number(b.vol !== undefined ? b.vol : (b.volume || 0));
            var barX = (i + 0.5) * stepX - barW / 2;
            var barH = Math.max(3, (v / (maxVol || 1)) * chartH);
            var barY = yZero - barH;
            var fill = b.is_bull ? 'rgba(16, 185, 129, 0.75)' : 'rgba(244, 63, 94, 0.75)';
            var stroke = b.is_bull ? '#10b981' : '#f43f5e';
            barsHtml += '<rect x="' + barX.toFixed(1) + '" y="' + barY.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + barH.toFixed(1) + '" fill="' + fill + '" stroke="' + stroke + '" stroke-width="1" rx="2" ry="2" />';
        });
        realBarsGroup.innerHTML = barsHtml;
    }

    // CVD 꺾은선 (<path id="cvd-line-path">)
    var linePath = document.getElementById('cvd-line-path');
    if (linePath && cvdVals.length) {
        var minCvd = Math.min.apply(null, cvdVals);
        var maxCvd = Math.max.apply(null, cvdVals);
        var cvdSpan = (maxCvd - minCvd) || 1;

        var pathD = '';
        bars.forEach(function(b, i) {
            var cVal = Number(b.cvd_line !== undefined ? b.cvd_line : (b.cvd || 0));
            var ptX = (i + 0.5) * stepX;
            var cvdRatio = (cVal - minCvd) / cvdSpan;
            var ptY = yZero - (cvdRatio * chartH * 0.88 + chartH * 0.06);
            if (i === 0) pathD += 'M ' + ptX.toFixed(1) + ' ' + ptY.toFixed(1);
            else pathD += ' L ' + ptX.toFixed(1) + ' ' + ptY.toFixed(1);
        });
        linePath.setAttribute('d', pathD);
        linePath.setAttribute('stroke', '#818cf8');
        linePath.setAttribute('stroke-width', '2.5');
        linePath.setAttribute('fill', 'none');
        linePath.setAttribute('stroke-linecap', 'round');
        linePath.setAttribute('stroke-linejoin', 'round');
    }

    // 세로 보조선 (<g id="cvd-vertical-grids">)
    var vGridGroup = document.getElementById('cvd-vertical-grids');
    if (vGridGroup) {
        var vGridHtml = '';
        var gridStep = Math.max(1, Math.floor(bars.length / 6));
        for (var gi = 0; gi < bars.length; gi += gridStep) {
            var gx = (gi + 0.5) * stepX;
            vGridHtml += '<line x1="' + gx.toFixed(1) + '" y1="' + yTop.toFixed(1) + '" x2="' + gx.toFixed(1) + '" y2="' + yZero.toFixed(1) + '" stroke="rgba(51, 65, 85, 0.4)" stroke-width="1" stroke-dasharray="3,3" />';
        }
        vGridGroup.innerHTML = vGridHtml;
    }

    cvdBarsCache = bars;
}

// 4. 마우스 이동 시 실시간 봉 상세 탐색기
function initCvdInteraction() {
    var svg = document.getElementById('cvd-bars-svg');
    if (!svg) return;

    svg.addEventListener('mousemove', function(e) {
        if (!cvdBarsCache || !cvdBarsCache.length) return;
        var rect = svg.getBoundingClientRect();
        var mouseX = e.clientX - rect.left;
        var stepX = rect.width / cvdBarsCache.length;
        var idx = Math.min(cvdBarsCache.length - 1, Math.max(0, Math.floor(mouseX / stepX)));
        var bar = cvdBarsCache[idx];
        if (!bar) return;

        safeSet('cvd-inspect-label', formatEtTime(bar.t) + ' ET (' + (bar.is_bull ? '매수' : '매도') + ')');
        safeSet('cvd-recent-vol', fmtCvdVal(bar.vol, false));
        safeSet('cvd-inspect-sub', 'CVD ' + fmtCvdVal(bar.cvd_line, true));
    });

    svg.addEventListener('mouseleave', function() {
        if (!cvdBarsCache || !cvdBarsCache.length) return;
        var lastBar = cvdBarsCache[cvdBarsCache.length - 1];
        safeSet('cvd-inspect-label', '마지막 봉');
        safeSet('cvd-recent-vol', fmtCvdVal(lastBar.vol, false));
        safeSet('cvd-inspect-sub', '최근 봉');
    });
}

document.addEventListener('DOMContentLoaded', initCvdInteraction);
