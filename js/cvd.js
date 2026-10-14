var currentCvdTf = '10m';
var currentCvdData = null;
var cvdBarsCache = [];

function safeSet(id, val) {
    var el = document.getElementById(id);
    if (el && val !== undefined && val !== null) {
        el.textContent = val;
    }
}

// 백엔드 vol(천 주 단위)을 실제 주 단위로 환산하여 M(밀리언) / K 표기
function fmtVolM(shares) {
    if (shares === null || shares === undefined || isNaN(shares)) return '--';
    var abs = Math.abs(shares);
    if (abs >= 1000000) return (shares / 1000000).toFixed(2) + 'M';
    if (abs >= 1000) return (shares / 1000).toFixed(0) + 'K';
    return Math.round(shares).toString();
}

// 좌측 Y축 눈금용 간결한 M / K 표기
function fmtYAxisVol(shares) {
    if (shares === null || shares === undefined || isNaN(shares)) return '--';
    var abs = Math.abs(shares);
    if (abs >= 1000000) return (shares / 1000000).toFixed(1) + 'M';
    if (abs >= 1000) return Math.round(shares / 1000) + 'K';
    return Math.round(shares).toString();
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

// 타임프레임 버튼 클릭 연동 (1m / 5m / 10m / 15m / 30m / 1H)
function changeCvdTimeframe(tf) {
    if (!tf) return;
    currentCvdTf = tf;

    var btns = document.querySelectorAll('#cvd-tf-group button, [data-cvd-tf]');
    btns.forEach(function(btn) {
        var bText = (btn.getAttribute('data-cvd-tf') || btn.innerText || '').trim().toLowerCase();
        if (bText === tf.toLowerCase()) {
            btn.className = 'px-2.5 py-1 text-xs font-mono font-bold bg-emerald-600 text-white rounded shadow-sm';
        } else {
            btn.className = 'px-2.5 py-1 text-xs font-mono font-semibold bg-slate-800 text-slate-300 hover:text-white rounded';
        }
    });

    if (typeof fetchRealMarketData === 'function') {
        fetchRealMarketData();
    }
}
window.changeCvdTimeframe = changeCvdTimeframe;
window.setCvdTimeframe = changeCvdTimeframe;

function renderCvd(cvd) {
    if (!cvd) return;
    if (cvd.cvd && !cvd.bars) cvd = cvd.cvd;
    currentCvdData = cvd;

    var bars = cvd.bars || cvd.series || cvd.data || cvd.candles || [];
    if (!Array.isArray(bars) || bars.length === 0) return;

    var tfLabel = (cvd.timeframe || currentCvdTf || '10m');
    var srcLabel = cvd.source || ('Charles Schwab (SPY ' + tfLabel + ')');

    // 1. 상단 헤더 및 뱃지 복원
    safeSet('cvd-title-tf', tfLabel.toUpperCase());
    safeSet('cvd-source', srcLabel);
    safeSet('cvd-data-time', 'Data as of ' + (cvd.data_time || '--'));

    var priorBadge = document.getElementById('cvd-prior-badge');
    if (priorBadge) {
        priorBadge.classList.remove('hidden');
        if (cvd.is_prior) {
            priorBadge.innerHTML = '🟡 전일 정규장 마감';
        } else {
            priorBadge.innerHTML = '🟢 당일 정규장 실시간';
        }
    }

    // 2. 거래량 합산 및 백엔드 정밀 Buy/Sell 데이터 우선 적용
    var rawSum = 0;
    bars.forEach(function(b) { rawSum += Number(b.vol || b.volume || 0); });
    var unitMult = rawSum < 500000 ? 1000 : 1;

    var maxVolShares = 1000;
    var totalVolShares = 0;
    var cvdVals = [];

    bars.forEach(function(b) {
        var vShares = Number(b.vol !== undefined ? b.vol : (b.volume || 0)) * unitMult;
        if (vShares > maxVolShares) maxVolShares = vShares;
        totalVolShares += vShares;
        cvdVals.push(Number(b.cvd_line !== undefined ? b.cvd_line : (b.cvd || 0)));
    });

    // 백엔드가 정밀 계산한 buy_pct / sell_pct / buy_vol / sell_vol을 최우선 사용 (막대 색상 100% 쏠림 버그 해결)
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

    // 집계 구간 및 데이터 설명 복원
    safeSet('cvd-agg-range', cvd.aggregate_range || (sDate + ' 정규장 (' + tStart + ' ~ ' + tEndFull + ') · ' + bars.length + '개 ' + tfLabel + ' 봉'));
    safeSet('cvd-data-desc', cvd.data_desc || ('SPY 정규장 · ' + srcLabel + ' · 체결 압력 CVD'));

    // 우측 상단 Buying / Selling Pressure 뱃지 복원
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

    // 3. 좌측 Y축 눈금 (선명한 M / K 단위 표시)
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

    // 4. 하단 밀리언(M) 거래량 및 Buy/Sell 상세 수치 복원
    safeSet('cvd-inspect-label', '마지막 봉');
    safeSet('cvd-last-time', cvd.data_time || (sDate + ' ' + tEndFull));
    safeSet('cvd-inspect-sub', '최근 봉');
    safeSet('cvd-recent-vol', cvd.recent_vol || fmtVolM(lastBarShares));
    safeSet('cvd-total-vol', cvd.total_vol || fmtVolM(totalVolShares));

    safeSet('cvd-buy-pct', '▲ Buy ' + buyPctRound + '% (' + buyVolText + ')');
    safeSet('cvd-sell-pct', '▼ Sell ' + sellPctRound + '% (' + sellVolText + ')');

    var barFill = document.getElementById('cvd-bar-fill');
    if (barFill) barFill.style.width = buyPctRound + '%';
    var sellFill = document.getElementById('cvd-sell-fill');
    if (sellFill) sellFill.style.width = sellPctRound + '%';

    safeSet('cvd-summary-text', cvd.summary_text || cvd.summary || ('CVD Flow: Buy ' + buyPctRound + '% / Sell ' + sellPctRound + '% in session.'));

    // 5. SVG 차트 렌더링
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

    // (A) 30분 간격 세로 점선 및 하단 시간(09:30 ~ 16:00) 텍스트 렌더링
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
        vGridGroup.innerHTML = gridHtml;
    }

    // (B) 거래량 막대 렌더링 (<g id="cvd-real-bars">)
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

    // (C) 노란색 CVD 곡선 렌더링 (<path id="cvd-line-path">)
    var linePath = document.getElementById('cvd-line-path');
    if (linePath && cvdVals.length) {
        var minCvd = Math.min.apply(null, cvdVals);
        var maxCvd = Math.max.apply(null, cvdVals);
        var cvdSpan = (maxCvd - minCvd) || 1;

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

// 마우스/터치 이동 시 개별 봉 거래량 확인
function initCvdInteraction() {
    var svg = document.getElementById('cvd-bars-svg');
    if (!svg) return;

    svg.addEventListener('mousemove', function(e) {
        if (!cvdBarsCache || !cvdBarsCache.bars || !cvdBarsCache.bars.length) return;
        var rect = svg.getBoundingClientRect();
        var relX = (e.clientX - rect.left) / rect.width;
        var idx = Math.min(cvdBarsCache.bars.length - 1, Math.max(0, Math.floor(relX * cvdBarsCache.bars.length)));
        var bar = cvdBarsCache.bars[idx];
        if (!bar) return;

        var vShares = Number(bar.vol || 0) * cvdBarsCache.unitMult;
        safeSet('cvd-inspect-label', '선택 봉');
        safeSet('cvd-last-time', (cvdBarsCache.sDate ? cvdBarsCache.sDate + ' ' : '') + formatEtTime(bar.t) + ':00 ET');
        safeSet('cvd-inspect-sub', bar.is_bull ? '매수 우세 봉' : '매도 우세 봉');
        safeSet('cvd-recent-vol', fmtVolM(vShares));
    });

    svg.addEventListener('mouseleave', function() {
        if (!cvdBarsCache || !cvdBarsCache.bars || !cvdBarsCache.bars.length) return;
        safeSet('cvd-inspect-label', '마지막 봉');
        safeSet('cvd-last-time', currentCvdData.data_time || (cvdBarsCache.sDate + ' ' + cvdBarsCache.tEndFull));
        safeSet('cvd-inspect-sub', '최근 봉');
        safeSet('cvd-recent-vol', fmtVolM(cvdBarsCache.lastBarShares));
    });
}

document.addEventListener('DOMContentLoaded', initCvdInteraction);
