var currentCvdTf = '10m';
var currentCvdData = null;
var cvdBarsCache = [];

// app.js의 API_URL 상수 재사용 (배포 URL 변경 대응)
function cvdApiUrl() {
    try { return API_URL; } catch (e) { return 'https://0-dte-seven.vercel.app/api/market-data'; }
}

function safeSet(id, val) {
    var el = document.getElementById(id);
    if (el && val !== undefined && val !== null) {
        el.textContent = val;
    }
}

function fmtVolM(shares) {
    if (shares === null || shares === undefined || isNaN(shares)) return '--';
    var abs = Math.abs(shares);
    if (abs >= 1000000) return (shares / 1000000).toFixed(2) + 'M';
    if (abs >= 1000) return (shares / 1000).toFixed(0) + 'K';
    return Math.round(shares).toString();
}

function fmtYAxisVol(shares) {
    if (shares === null || shares === undefined || isNaN(shares)) return '--';
    var abs = Math.abs(shares);
    if (abs >= 1000000) return (shares / 1000000).toFixed(1) + 'M';
    if (abs >= 1000) return Math.round(shares / 1000) + 'K';
    return Math.round(shares).toString();
}

// 부호 포함 볼륨 표기 (CVD 값용: +1.25M / -800K)
function fmtSignedM(shares) {
    if (shares === null || shares === undefined || isNaN(shares)) return '--';
    var s = fmtVolM(shares);
    return (shares > 0 ? '+' : '') + s;
}

function formatEtTime(unixSec) {

    if (!unixSec) return '--';

    return new Date(unixSec * 1000)
        .toLocaleTimeString(
            'en-US',
            {
                timeZone: 'America/New_York',
                hour12: false,
                hour: '2-digit',
                minute: '2-digit'
            }
        );
}

// Qabduun 1m / 5m / 10m / 15m / 30m / 1H yeroo cuqaasamu kallattiin tf sirrii waama
function changeCvdTimeframe(tf) {
    if (!tf) return;
    currentCvdTf = tf.toLowerCase();
    window.currentCvdTf = currentCvdTf;
    window.cvdTf = currentCvdTf;

    // 버튼 스타일 토글 (반응형 클래스 유지 — className 덮어쓰기 금지)
    var btns = document.querySelectorAll('#cvd-tf-group button');
    btns.forEach(function(btn) {
        var bText = (btn.getAttribute('data-tf') || btn.innerText || '').trim().toLowerCase();
        var active = (bText === currentCvdTf);
        btn.classList.toggle('bg-teal-600', active);
        btn.classList.toggle('text-white', active);
        btn.classList.toggle('font-bold', active);
        btn.classList.toggle('shadow', active);
        btn.classList.toggle('bg-slate-800/80', !active);
        btn.classList.toggle('text-slate-300', !active);
        btn.classList.toggle('hover:bg-slate-700', !active);
    });

    // 5m cuqaasamee 1m akka hin agarsiisneef kallattiin API cvd_tf waliin waama
    fetch(cvdApiUrl() + '?cvd_tf=' + encodeURIComponent(currentCvdTf) + '&_t=' + Date.now())
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d && d.cvd) {
                renderCvd(d.cvd);
            }
        })
        .catch(function() {
            if (typeof fetchRealMarketData === 'function') fetchRealMarketData();
        });
}
window.changeCvdTimeframe = changeCvdTimeframe;
window.setCvdTimeframe = changeCvdTimeframe;

function renderCvd(cvd) {
    if (!cvd) return;
    if (cvd.cvd && !cvd.bars) cvd = cvd.cvd;

    var bars = cvd.bars || cvd.series || cvd.data || cvd.candles || [];
    if (!Array.isArray(bars) || bars.length === 0) return;

    // Auto-refresh yeroo dhufu tf filatamee jiru (fakkeenyaaf 5m) chaartii 1mtiin akka hin balleessine eega
    var incomingSource = String(cvd.source || '');
    var expectedTag = 'SPY ' + (currentCvdTf === '1h' ? '1H' : currentCvdTf);
    if (incomingSource.indexOf('SPY ') !== -1 && incomingSource.indexOf(expectedTag) === -1) {
        fetch(cvdApiUrl() + '?cvd_tf=' + encodeURIComponent(currentCvdTf) + '&_t=' + Date.now())
            .then(function(r) { return r.json(); })
            .then(function(d) { if (d && d.cvd) renderCvdDirect(d.cvd); })
            .catch(function() {});
        return;
    }

    renderCvdDirect(cvd);
}

function renderCvdDirect(cvd) {
    currentCvdData = cvd;
    var bars = cvd.bars || [];
    if (!bars.length) return;

    var tfLabel = (currentCvdTf === '1h' ? '1H' : currentCvdTf);
    var srcLabel = cvd.source || ('Charles Schwab (SPY ' + tfLabel + ')');

    safeSet('cvd-title-tf', tfLabel.toUpperCase());
    safeSet('cvd-source', srcLabel);
    safeSet('cvd-data-time', 'Data as of ' + (cvd.data_time || '--'));
    safeSet('cvd-x-caption', 'Time (Eastern Time, ET) · ' + tfLabel + ' Intervals');

    var priorBadge = document.getElementById('cvd-prior-badge');
    if (priorBadge) {
        priorBadge.classList.remove('hidden');
        priorBadge.innerHTML = cvd.is_prior ? '🟡 전일 정규장 마감' : '🟢 당일 정규장 실시간';
    }

    // 백엔드가 명시한 단위 배율 사용 (휴리스틱 추측 제거)
    var unitMult = Number(cvd.vol_scale) > 0 ? Number(cvd.vol_scale) : 1000;

    var maxVolShares = 1000;
    var totalVolShares = 0;
    var cvdVals = [0]; // 0 irraa jalqabuun sararri CVD akka faallaa hin deemne taasisa

    bars.forEach(function(b) {
        var vShares = Number(b.vol !== undefined ? b.vol : (b.volume || 0)) * unitMult;
        if (vShares > maxVolShares) maxVolShares = vShares;
        totalVolShares += vShares;
        cvdVals.push(Number(b.cvd_line !== undefined ? b.cvd_line : (b.cvd || 0)));
    });

    // CVD 라인 정규화용 min/max (우측 축 라벨과 라인 렌더링이 공유)
    var minCvd = Math.min.apply(null, cvdVals);
    var maxCvd = Math.max.apply(null, cvdVals);
    var cvdSpan = (maxCvd - minCvd) || 1;

    var buyPctRound = (cvd.buy_pct !== undefined && cvd.buy_pct !== null) ? Number(cvd.buy_pct) : 50;
    var sellPctRound = (cvd.sell_pct !== undefined && cvd.sell_pct !== null) ? Number(cvd.sell_pct) : (100 - buyPctRound);

    var totalBuyShares = Math.round(totalVolShares * (buyPctRound / 100));
    var totalSellShares = Math.max(0, totalVolShares - totalBuyShares);

    var buyVolText = cvd.buy_vol || fmtVolM(totalBuyShares);
    var sellVolText = cvd.sell_vol || fmtVolM(totalSellShares);

    var firstBar = bars[0];
    var lastBar = bars[bars.length - 1];
    var lastBarShares = Number(lastBar.vol !== undefined ? lastBar.vol : (lastBar.volume || 0)) * unitMult;

    var tStart = formatEtTime(firstBar.t);
    var tEndFull = cvd.last_bar_time || (formatEtTime(lastBar.t) + ':00 ET');
    var sDate = cvd.session_date || (cvd.data_time ? cvd.data_time.split(' ')[0] : '');

    safeSet('cvd-agg-range', cvd.aggregate_range || (sDate + ' 정규장 (' + tStart + ' ~ ' + tEndFull + ') · ' + bars.length + '개 ' + tfLabel + ' 봉'));
    safeSet('cvd-data-desc', cvd.data_desc || ('SPY 정규장 · ' + srcLabel + ' · 체결 압력 CVD'));

    var pill = document.getElementById('cvd-status-pill');
    if (pill) {
        if (buyPctRound >= 53) {
            pill.textContent = '↑ Buying Pressure';
            pill.className = 'text-xs font-bold px-2.5 py-1 rounded bg-emerald-950/90 text-emerald-400 border border-emerald-700/60';
        } else if (buyPctRound <= 47) {
            pill.textContent = '↓ Selling Pressure';
            pill.className = 'text-xs font-bold px-2.5 py-1 rounded bg-rose-950/90 text-rose-400 border border-rose-700/60';
        } else {
            pill.textContent = '• Balanced';
            pill.className = 'text-xs font-bold px-2.5 py-1 rounded bg-slate-800 text-slate-300 border border-slate-700';
        }
    }

    function setYLabel(id, text, color) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = text;
        el.setAttribute('fill', color);
        el.style.fill = color;
        el.style.color = color;
        el.style.fontWeight = 'bold';
        el.style.fontSize = '10px';
        el.style.fontFamily = 'monospace';
    }
    setYLabel('cvd-y-max', fmtYAxisVol(maxVolShares), '#38bdf8');
    setYLabel('cvd-y-mid', fmtYAxisVol(maxVolShares / 2), '#e2e8f0');

    safeSet('cvd-inspect-label', '마지막 봉');
    safeSet('cvd-last-time', cvd.data_time || (sDate + ' ' + tEndFull));
    safeSet('cvd-inspect-sub', '최근 봉');
    safeSet('cvd-recent-vol', cvd.recent_vol || fmtVolM(lastBarShares));
    safeSet('cvd-total-vol', cvd.total_vol || fmtVolM(totalVolShares));
    var lastCvdShares = Number(lastBar.cvd_line !== undefined ? lastBar.cvd_line : (lastBar.cvd || 0)) * unitMult;
    safeSet('cvd-inspect-cvd', fmtSignedM(lastCvdShares));

    safeSet('cvd-buy-pct', '▲ Buy ' + buyPctRound + '% (' + buyVolText + ')');
    safeSet('cvd-sell-pct', '▼ Sell ' + sellPctRound + '% (' + sellVolText + ')');

    var barFill = document.getElementById('cvd-bar-fill');
    if (barFill) barFill.style.width = buyPctRound + '%';
    var sellFill = document.getElementById('cvd-sell-fill');
    if (sellFill) sellFill.style.width = sellPctRound + '%';

    safeSet('cvd-summary-text', cvd.summary_text || cvd.summary || ('CVD Flow: Buy ' + buyPctRound + '% / Sell ' + sellPctRound + '% in session.'));

    var svg = document.getElementById('cvd-bars-svg');
    if (!svg) return;

    var vGridGroup = document.getElementById('cvd-vertical-grids');
    if (vGridGroup) vGridGroup.innerHTML = '';

    var xStart = 36, xEnd = 585, yTop = 24, yZero = 130;
    var staticLines = [];
    var allLines = svg.querySelectorAll('line');
    for (var li = 0; li < allLines.length; li++) {
        var ln = allLines[li];
        if (vGridGroup && vGridGroup.contains(ln)) continue;
        var ly1 = parseFloat(ln.getAttribute('y1'));
        var ly2 = parseFloat(ln.getAttribute('y2'));
        if (!isNaN(ly1) && Math.abs(ly1 - ly2) < 1) {
            staticLines.push(ln);
        }
    }

    if (staticLines.length >= 2) {
        staticLines.sort(function(a, b) {
            return parseFloat(a.getAttribute('y1')) - parseFloat(b.getAttribute('y1'));
        });
        var topLn = staticLines[0];
        var botLn = staticLines[staticLines.length - 1];
        xStart = parseFloat(topLn.getAttribute('x1')) || 36;
        xEnd = parseFloat(topLn.getAttribute('x2')) || 585;
        yTop = parseFloat(topLn.getAttribute('y1')) || 24;
        yZero = parseFloat(botLn.getAttribute('y1')) || 130;
    }

    var chartW = xEnd - xStart;
    var chartH = yZero - yTop;
    var stepX = chartW / bars.length;
    var barW = Math.max(2, Math.min(18, stepX * 0.72));

    if (vGridGroup) {
        var gridHtml = '';
        bars.forEach(function(b, i) {
            var tStr = formatEtTime(b.t);
            var mins = tStr.split(':')[1];
            var isHalfHour = (mins === '00' || mins === '30');
            if (isHalfHour) {
                var gx = xStart + (i + 0.5) * stepX;
                gridHtml += '<line x1="' + gx.toFixed(1) + '" y1="' + yTop.toFixed(1) + '" x2="' + gx.toFixed(1) + '" y2="' + yZero.toFixed(1) + '" stroke="rgba(71, 85, 105, 0.35)" stroke-width="1" stroke-dasharray="2,3" />';
                gridHtml += '<text x="' + gx.toFixed(1) + '" y="' + (yZero + 13).toFixed(1) + '" fill="#94a3b8" font-size="9" font-family="monospace" text-anchor="middle">' + tStr + '</text>';
            }
        });
        var lastTimeStr = formatEtTime(lastBar.t);
        if (lastTimeStr !== '16:00') {
            gridHtml += '<line x1="' + xEnd.toFixed(1) + '" y1="' + yTop.toFixed(1) + '" x2="' + xEnd.toFixed(1) + '" y2="' + yZero.toFixed(1) + '" stroke="rgba(71, 85, 105, 0.35)" stroke-width="1" stroke-dasharray="2,3" />';
            gridHtml += '<text x="' + xEnd.toFixed(1) + '" y="' + (yZero + 13).toFixed(1) + '" fill="#94a3b8" font-size="9" font-family="monospace" text-anchor="middle">16:00</text>';
        }
        // CVD 우측 축 라벨 (CVD 라인은 자체 스케일로 정규화 — 좌측 볼륨 축과 무관)
        var yForCvd = function(cv) { return yZero - (((cv - minCvd) / cvdSpan) * (chartH * 0.82) + chartH * 0.08); };
        var midCvd = (maxCvd + minCvd) / 2;
        gridHtml += '<text x="' + (xEnd + 6).toFixed(1) + '" y="' + (yForCvd(maxCvd) + 3).toFixed(1) + '" fill="#fbbf24" font-size="9" font-family="monospace">' + fmtSignedM(maxCvd * unitMult) + '</text>';
        gridHtml += '<text x="' + (xEnd + 6).toFixed(1) + '" y="' + (yForCvd(midCvd) + 3).toFixed(1) + '" fill="#fbbf24" font-size="9" font-family="monospace">' + fmtSignedM(midCvd * unitMult) + '</text>';
        gridHtml += '<text x="' + (xEnd + 6).toFixed(1) + '" y="' + (yForCvd(minCvd) + 3).toFixed(1) + '" fill="#fbbf24" font-size="9" font-family="monospace">' + fmtSignedM(minCvd * unitMult) + '</text>';
        vGridGroup.innerHTML = gridHtml;
    }

    var realBarsGroup = document.getElementById('cvd-real-bars');
    if (realBarsGroup) {
        var barsHtml = '';
        bars.forEach(function(b, i) {
            var vShares = Number(b.vol !== undefined ? b.vol : (b.volume || 0)) * unitMult;
            var bx = xStart + (i + 0.5) * stepX - barW / 2;
            var bh = Math.max(2, (vShares / (maxVolShares || 1)) * chartH);
            var by = yZero - bh;
            var fill = b.is_bull ? 'rgba(16, 185, 129, 0.75)' : 'rgba(244, 63, 94, 0.75)';
            var stroke = b.is_bull ? '#10b981' : '#f43f5e';
            barsHtml += '<rect x="' + bx.toFixed(1) + '" y="' + by.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + bh.toFixed(1) + '" fill="' + fill + '" stroke="' + stroke + '" stroke-width="0.8" rx="1" />';
        });
        realBarsGroup.innerHTML = barsHtml;
    }

    // (C) Sarara keelloo CVD (0 기준선 포함하여 1H에서도 방향 왜곡 방지)
    // minCvd/maxCvd/cvdSpan은 상단에서 계산됨 (우측 축 라벨과 공유)
    var linePath = document.getElementById('cvd-line-path');
    if (linePath && cvdVals.length) {
        var pathD = '';
        bars.forEach(function(b, i) {
            var cVal = Number(b.cvd_line !== undefined ? b.cvd_line : (b.cvd || 0));
            var px = xStart + (i + 0.5) * stepX;
            var py = yZero - (((cVal - minCvd) / cvdSpan) * (chartH * 0.82) + chartH * 0.08);
            pathD += (i === 0 ? 'M ' : ' L ') + px.toFixed(1) + ' ' + py.toFixed(1);
        });
        linePath.setAttribute('d', pathD);
        linePath.setAttribute('stroke', '#fbbf24');
        linePath.setAttribute('stroke-width', '2');
        linePath.setAttribute('fill', 'none');
    }

    cvdBarsCache = { bars: bars, unitMult: unitMult, xStart: xStart, xEnd: xEnd, sDate: sDate, tEndFull: tEndFull, lastBarShares: lastBarShares };
}

function initCvdInteraction() {
    var svg = document.getElementById('cvd-bars-svg');
    if (!svg) return;

    function barCvdShares(bar, unit) {
        return Number(bar.cvd_line !== undefined ? bar.cvd_line : (bar.cvd || 0)) * unit;
    }

    function inspectAt(clientX) {
        if (!cvdBarsCache || !cvdBarsCache.bars || !cvdBarsCache.bars.length) return;
        var rect = svg.getBoundingClientRect();
        var relX = (clientX - rect.left) / rect.width;
        var idx = Math.min(cvdBarsCache.bars.length - 1, Math.max(0, Math.floor(relX * cvdBarsCache.bars.length)));
        var bar = cvdBarsCache.bars[idx];
        if (!bar) return;

        var vShares = Number(bar.vol !== undefined ? bar.vol : (bar.volume || 0)) * cvdBarsCache.unitMult;
        safeSet('cvd-inspect-label', '선택 봉');
        safeSet('cvd-last-time', (cvdBarsCache.sDate ? cvdBarsCache.sDate + ' ' : '') + formatEtTime(bar.t) + ':00 ET');
        safeSet('cvd-inspect-sub', bar.is_bull ? '매수 우세 봉' : '매도 우세 봉');
        safeSet('cvd-recent-vol', fmtVolM(vShares));
        safeSet('cvd-inspect-cvd', fmtSignedM(barCvdShares(bar, cvdBarsCache.unitMult)));
    }

    function resetInspect() {
        if (!cvdBarsCache || !cvdBarsCache.bars || !cvdBarsCache.bars.length) return;
        var lastBar = cvdBarsCache.bars[cvdBarsCache.bars.length - 1];
        safeSet('cvd-inspect-label', '마지막 봉');
        safeSet('cvd-last-time', (currentCvdData && currentCvdData.data_time) || (cvdBarsCache.sDate + ' ' + cvdBarsCache.tEndFull));
        safeSet('cvd-inspect-sub', '최근 봉');
        safeSet('cvd-recent-vol', fmtVolM(cvdBarsCache.lastBarShares));
        safeSet('cvd-inspect-cvd', fmtSignedM(barCvdShares(lastBar, cvdBarsCache.unitMult)));
    }

    svg.addEventListener('mousemove', function(e) { inspectAt(e.clientX); });
    svg.addEventListener('mouseleave', resetInspect);
    // 모바일 터치 지원
    svg.addEventListener('touchstart', function(e) {
        if (e.touches.length > 0) inspectAt(e.touches[0].clientX);
    }, { passive: true });
    svg.addEventListener('touchmove', function(e) {
        if (e.touches.length > 0) inspectAt(e.touches[0].clientX);
    }, { passive: true });
    svg.addEventListener('touchend', resetInspect);
}

document.addEventListener('DOMContentLoaded', initCvdInteraction);
