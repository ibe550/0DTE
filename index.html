"""SPX 0DTE DEFENDER - market-data API (FastAPI on Vercel)

데이터 우선순위: Charles Schwab -> Yahoo Finance (자동 대체).
두 곳 모두 실패하면 값을 지어내지 않고 None(= 화면의 N/A)을 반환합니다.
모든 블록은 실제로 사용한 데이터 출처를 "source" 필드로 돌려줍니다.
"""
import math
import os
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytz
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
handler = app
application = app

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ET = pytz.timezone("US/Eastern")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SCHWAB_BASE_URL = "https://api.schwabapi.com/marketdata/v1"
SRC_SCHWAB = "Charles Schwab"
SRC_YAHOO = "Yahoo Finance"
SECONDS_PER_YEAR = 365.0 * 24 * 3600


# ─────────────────────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────────────────────
def num(x):
    """유한한 float 이면 float, 아니면 None (NaN / inf / 문자열 방어)."""
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


_CACHE = {}


def cached(key, ttl, fn):
    """아주 짧은 TTL 캐시. 성공한 결과(None 아님)만 저장합니다."""
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    if val is not None:
        _CACHE[key] = (now, val)
    return val


def fmt_dollars(x):
    sign = "+" if x >= 0 else "-"
    a = abs(x)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if a >= div:
            return f"{sign}{a / div:.1f}{unit}"
    return f"{sign}{a:.0f}"


def src_kind(s):
    if not s:
        return "na"
    if s.startswith(SRC_SCHWAB):
        return "schwab"
    if s.startswith(SRC_YAHOO):
        return "yahoo"
    return "other"


# ─────────────────────────────────────────────────────────────
# Schwab 인증 / 호출
# ─────────────────────────────────────────────────────────────
_TOKEN = {"value": None, "exp": 0.0}


def get_schwab_token():
    """(access_token | None, 상태 메시지). access token 은 만료 전까지 재사용합니다."""
    now = time.time()
    if _TOKEN["value"] and now < _TOKEN["exp"]:
        return _TOKEN["value"], "연결됨"

    app_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_SECRET")
    refresh_token = os.environ.get("SCHWAB_REFRESH_TOKEN")
    if not app_key or not refresh_token:
        return None, "Schwab 환경변수 없음 (SCHWAB_APP_KEY / SCHWAB_REFRESH_TOKEN)"

    try:
        res = requests.post(
            "https://api.schwabapi.com/v1/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": app_key},
            auth=(app_key, app_secret) if app_secret else None,
            timeout=4,
        )
    except Exception as e:
        return None, f"Schwab 토큰 요청 오류 ({type(e).__name__})"

    if res.status_code == 200:
        try:
            body = res.json()
        except Exception:
            body = {}
        token = body.get("access_token")
        if token:
            ttl = int(num(body.get("expires_in")) or 1800)
            _TOKEN["value"] = token
            _TOKEN["exp"] = now + max(60, ttl - 120)
            return token, "연결됨"

    hint = ""
    if res.status_code in (400, 401):
        hint = " - refresh token 만료(7일마다 재발급 필요) 또는 키/시크릿 확인"
    return None, f"Schwab 토큰 갱신 실패 (HTTP {res.status_code}){hint}"


def schwab_get(token, path, params=None, timeout=4):
    if not token:
        return None
    try:
        r = requests.get(
            f"{SCHWAB_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params=params,
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401:
            _TOKEN["value"] = None  # 다음 요청에서 토큰 재발급
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────
# 시세 (Schwab 우선 -> Yahoo)
# ─────────────────────────────────────────────────────────────
# key: (Schwab 심볼, Yahoo 심볼)   ※ Yahoo 의 S&P500 지수 심볼은 ^GSPC 입니다 (^SPX 는 없음)
QUOTES = OrderedDict([
    ("spx", ("$SPX", "^GSPC")),
    ("es", ("/ES", "ES=F")),
    ("vix", ("$VIX", "^VIX")),
    ("vix9d", ("$VIX9D", "^VIX9D")),
    ("mag7", ("MAGS", "MAGS")),
    ("spy", ("SPY", "SPY")),
    ("tnx", ("$TNX", "^TNX")),
    ("tyx", ("$TYX", "^TYX")),
    ("irx", ("$IRX", "^IRX")),
])


def make_quote(price, prev, change, source):
    price = num(price)
    if price is None:
        return None
    prev = num(prev)
    change = num(change)
    if change is None and prev is not None:
        change = price - prev
    if prev is None and change is not None:
        prev = price - change
    pct = (change / prev * 100.0) if (change is not None and prev) else None
    return {
        "price": price,
        "change": round(change, 2) if change is not None else None,
        "change_pct": round(pct, 2) if pct is not None else None,
        "source": source,
    }


def fetch_schwab_quotes(token, symbols):
    out = {}
    data = schwab_get(token, "/quotes", {"symbols": ",".join(symbols), "fields": "quote"})
    if not isinstance(data, dict):
        return out
    for sym in symbols:
        entry = data.get(sym)
        q = entry.get("quote") if isinstance(entry, dict) else None
        if not isinstance(q, dict):
            continue
        price = q.get("lastPrice") or q.get("mark")
        item = make_quote(price, q.get("closePrice"), q.get("netChange"), f"{SRC_SCHWAB} ({sym})")
        if item:
            out[sym] = item
    return out


def fetch_yahoo_chart(symbol, interval="5m", range_str="1d"):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_str}"
        res = requests.get(url, headers=HEADERS, timeout=4)
        if res.status_code == 200:
            result = (res.json().get("chart", {}).get("result") or [{}])[0]
            return result or {}
    except Exception:
        pass
    return {}


def fetch_yahoo_quote(ysym):
    meta = fetch_yahoo_chart(ysym, "5m", "1d").get("meta") or {}
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    return make_quote(meta.get("regularMarketPrice"), prev, None, f"{SRC_YAHOO} ({ysym})")


def get_all_quotes(token):
    def load():
        result = {}
        symbols = [s for s, _ in QUOTES.values()]
        schwab = fetch_schwab_quotes(token, symbols) if token else {}
        if token and not schwab:
            # 묶음 요청이 통째로 실패한 경우(심볼 하나가 문제일 수 있음): $SPX 가 되는지 확인 후 개별 조회
            if fetch_schwab_quotes(token, ["$SPX"]):
                with ThreadPoolExecutor(max_workers=len(symbols)) as ex:
                    for part in ex.map(lambda sym: fetch_schwab_quotes(token, [sym]), symbols):
                        schwab.update(part)
        need = []
        for key, (ssym, _y) in QUOTES.items():
            if ssym in schwab:
                result[key] = schwab[ssym]
            else:
                need.append(key)
        if need:
            with ThreadPoolExecutor(max_workers=len(need)) as ex:
                futs = {k: ex.submit(fetch_yahoo_quote, QUOTES[k][1]) for k in need}
            for k, f in futs.items():
                try:
                    result[k] = f.result()
                except Exception:
                    result[k] = None
        return result if any(result.values()) else None

    return cached("quotes", 4, load) or {}


# ─────────────────────────────────────────────────────────────
# 봉(candle) 데이터 (Schwab pricehistory 우선 -> Yahoo chart)
# ─────────────────────────────────────────────────────────────
# tf -> (Yahoo interval, Yahoo range, Schwab 분봉 단위, Schwab 조회 일수, 합칠 분 단위)
TF_SPEC = {
    "1m": ("1m", "2d", 1, 2, None),
    "5m": ("5m", "5d", 5, 5, None),
    "15m": ("15m", "5d", 15, 5, None),
    "30m": ("30m", "5d", 30, 5, None),
    "1h": ("60m", "1mo", 30, 10, 60),  # Schwab 은 60분봉이 없어 30분봉을 합칩니다
}
TF_LABEL = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H"}
INSTR = {"spx": ("$SPX", "^GSPC"), "spy": ("SPY", "SPY"), "es": (None, "ES=F")}


def normalize_tf(tf):
    key = str(tf or "").strip().lower()
    return key if key in TF_SPEC else "1h"


def yahoo_candles(symbol, interval, range_str):
    chart = fetch_yahoo_chart(symbol, interval, range_str)
    ts = chart.get("timestamp") or []
    quote = ((chart.get("indicators") or {}).get("quote") or [{}])[0] or {}
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    vols = quote.get("volume") or []
    out = []
    for i, t in enumerate(ts):
        if i >= len(closes) or i >= len(opens) or i >= len(highs) or i >= len(lows):
            break
        o, h, l, c = num(opens[i]), num(highs[i]), num(lows[i]), num(closes[i])
        if None in (o, h, l, c):
            continue  # 값이 비어 있는 봉은 통째로 건너뜁니다 (배열이 어긋나지 않도록)
        v = num(vols[i]) if i < len(vols) else 0.0
        out.append({"t": int(t), "o": o, "h": h, "l": l, "c": c, "v": v or 0.0})
    return out


def schwab_candles(token, symbol, freq, days):
    data = schwab_get(
        token,
        "/pricehistory",
        {
            "symbol": symbol,
            "periodType": "day",
            "period": days,
            "frequencyType": "minute",
            "frequency": freq,
            "needExtendedHoursData": "false",
        },
        timeout=5,
    )
    out = []
    if not isinstance(data, dict):
        return out
    for cd in data.get("candles") or []:
        if not isinstance(cd, dict):
            continue
        o, h, l, c, t = num(cd.get("open")), num(cd.get("high")), num(cd.get("low")), num(cd.get("close")), num(cd.get("datetime"))
        if None in (o, h, l, c, t):
            continue
        out.append({"t": int(t / 1000), "o": o, "h": h, "l": l, "c": c, "v": num(cd.get("volume")) or 0.0})
    return out


def aggregate_candles(candles, minutes):
    """분봉을 미국 정규장 시작(09:30 ET) 기준으로 minutes 단위 봉으로 합칩니다."""
    groups = OrderedDict()
    for cd in candles:
        dt = datetime.fromtimestamp(cd["t"], ET)
        key = (dt.date(), (dt.hour * 60 + dt.minute - 570) // minutes)
        g = groups.get(key)
        if g is None:
            groups[key] = dict(cd)
        else:
            g["h"] = max(g["h"], cd["h"])
            g["l"] = min(g["l"], cd["l"])
            g["c"] = cd["c"]
            g["v"] += cd["v"]
    return list(groups.values())


def get_candles(token, inst, tf):
    """{"candles": [...], "source": "..."} 또는 None."""
    key = normalize_tf(tf)

    def load():
        y_int, y_rng, s_freq, s_days, agg = TF_SPEC[key]
        ssym, ysym = INSTR[inst]
        if token and ssym:
            cs = schwab_candles(token, ssym, s_freq, s_days)
            if cs:
                if agg:
                    cs = aggregate_candles(cs, agg)
                return {"candles": cs, "source": f"{SRC_SCHWAB} ({ssym} {TF_LABEL[key]})"}
        cs = yahoo_candles(ysym, y_int, y_rng)
        if cs:
            return {"candles": cs, "source": f"{SRC_YAHOO} ({ysym} {y_int})"}
        return None

    return cached(f"candles:{inst}:{key}", 10 if key in ("1m", "5m") else 30, load)


def last_session(candles):
    if not candles:
        return []
    d = datetime.fromtimestamp(candles[-1]["t"], ET).date()
    return [c for c in candles if datetime.fromtimestamp(c["t"], ET).date() == d]


def et_label(ts):
    return datetime.fromtimestamp(ts, ET).strftime("%m/%d %H:%M ET")


def et_label_sec(ts):
    return datetime.fromtimestamp(ts, ET).strftime("%m/%d %H:%M:%S ET")


def et_time_sec(ts):
    return datetime.fromtimestamp(ts, ET).strftime("%H:%M:%S ET")


def fmt_vol(v):
    """거래량 표시용 포맷 (부호 없음): 1234 -> '1.2K', 1_270_000 -> '1.27M'."""
    v = float(v)
    if v >= 1e6:
        return f"{v / 1e6:.2f}M"
    if v >= 1e3:
        return f"{v / 1e3:.1f}K"
    return f"{v:.0f}"


# ─────────────────────────────────────────────────────────────
# 지표: EMA / RSI
# ─────────────────────────────────────────────────────────────
def ema_series(values, period):
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _rsi_value(avg_gain, avg_loss):
    if avg_loss == 0:
        return 50.0 if avg_gain == 0 else 100.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def rsi_series(closes, period=14):
    """Wilder RSI. 데이터가 모자라면 빈 리스트 (가짜 50 을 만들지 않습니다)."""
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    out = [round(_rsi_value(avg_g, avg_l), 1)]
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        out.append(round(_rsi_value(avg_g, avg_l), 1))
    return out


# ─────────────────────────────────────────────────────────────
# VWAP / Volume Profile / CVD
# ─────────────────────────────────────────────────────────────
def compute_vwap(spy_candles, ratio, source):
    """당일(마지막 세션) 기준 VWAP. SPY -> SPX 환산(ratio). 밴드는 거래량 가중 표준편차."""
    sess = last_session(spy_candles)
    if not sess or not ratio:
        return None
    cum_v = cum_tp = cum_tp2 = 0.0
    series, u1, l1, u2, l2 = [], [], [], [], []
    sd = 0.0
    for c in sess:
        v = c["v"]
        if v <= 0:
            continue
        tp = (c["h"] + c["l"] + c["c"]) / 3.0 * ratio
        cum_v += v
        cum_tp += tp * v
        cum_tp2 += tp * tp * v
        vwap = cum_tp / cum_v
        sd = math.sqrt(max(cum_tp2 / cum_v - vwap * vwap, 0.0))
        series.append(round(vwap, 2))
        u1.append(round(vwap + sd, 2))
        l1.append(round(vwap - sd, 2))
        u2.append(round(vwap + 2 * sd, 2))
        l2.append(round(vwap - 2 * sd, 2))
    if not series:
        return None
    return {
        "val": series[-1],
        "sigma": round(sd, 2),
        "series": series,
        "upper1": u1,
        "lower1": l1,
        "upper2": u2,
        "lower2": l2,
        "data_time": et_label(sess[-1]["t"]),
        "source": f"{source} x SPX/SPY 환산 · 당일 VWAP · 밴드=거래량가중 표준편차",
    }


def last_rth_close(spx_candles):
    """가장 최근에 '완결된' 정규장의 마지막 SPX 봉 (기준 시각 + 종가).
    장이 열려 있는 동안 호출되면 오늘 봉은 아직 진행 중이라 노이즈가 있으므로,
    반드시 전 거래일(가장 최근 완결 세션)의 마지막 봉을 씁니다. 그래야 베이시스가
    '어제 정규장이 끝난 그 순간'처럼 SPX·ES 둘 다 안정적으로 확정된 값이 됩니다."""
    if not spx_candles:
        return None
    last_date = datetime.fromtimestamp(spx_candles[-1]["t"], ET).date()
    today = datetime.now(ET).date()
    if last_date < today:
        # 장 마감 후(또는 주말)라 가장 최근 봉 자체가 이미 완결된 세션입니다.
        return spx_candles[-1]
    prior = [c for c in spx_candles if datetime.fromtimestamp(c["t"], ET).date() < today]
    return prior[-1] if prior else None


VP_WINDOW_HOURS = 24
BASIS_MAX_GAP_SEC = 20 * 60  # SPX 봉과 ES 봉 시각이 20분 넘게 벌어지면 베이시스를 신뢰하지 않습니다


def compute_volume_profile(es_candles, spx_candles, es_source, spx_source):
    """ES=F 의 정규장+프리/애프터마켓(확장세션) 거래량을, '마지막 정규장 베이시스'로
    SPX 가격대에 매핑해서 만드는 Volume Profile. SPX 는 장중에만 거래되므로,
    가장 최근 SPX 정규장 종가와 그 시각의 ES 가격 차이(베이시스)를 한 번 구한 뒤
    그 값을 야간·프리마켓 ES 가격에도 그대로 더해 'SPX 환산가'로 씁니다."""
    anchor = last_rth_close(spx_candles)
    if not anchor or not es_candles:
        return None
    es_at_anchor = min(es_candles, key=lambda c: abs(c["t"] - anchor["t"]))
    if abs(es_at_anchor["t"] - anchor["t"]) > BASIS_MAX_GAP_SEC:
        return None
    basis = anchor["c"] - es_at_anchor["c"]  # SPX = ES + basis

    cutoff = es_candles[-1]["t"] - VP_WINDOW_HOURS * 3600
    window = [c for c in es_candles if c["t"] >= cutoff and c["v"] > 0]
    if not window:
        return None

    bins, total = {}, 0.0
    for c in window:
        lo, hi = c["l"] + basis, c["h"] + basis
        if hi < lo:
            lo, hi = hi, lo
        lo_b, hi_b = int(round(lo / 5.0)) * 5, int(round(hi / 5.0)) * 5
        rng = list(range(lo_b, hi_b + 5, 5))
        each = c["v"] / len(rng)
        for b in rng:
            bins[b] = bins.get(b, 0.0) + each
            total += each
    if not bins:
        return None
    keys = sorted(bins)
    poc = max(bins, key=bins.get)
    target = total * 0.70
    cur = bins[poc]
    lo_i = hi_i = keys.index(poc)
    while cur < target and (lo_i > 0 or hi_i < len(keys) - 1):
        up = bins[keys[hi_i + 1]] if hi_i + 1 < len(keys) else -1.0
        dn = bins[keys[lo_i - 1]] if lo_i > 0 else -1.0
        if up >= dn:
            hi_i += 1
            cur += up
        else:
            lo_i -= 1
            cur += dn
    hours_covered = (window[-1]["t"] - window[0]["t"]) / 3600.0
    return {
        "val": float(keys[lo_i]),
        "poc": float(poc),
        "vah": float(keys[hi_i]),
        "basis": round(basis, 2),
        "hours_covered": round(hours_covered, 1),
        "source": (
            f"{es_source} · 마지막 정규장 베이시스({basis:+.2f}pt, 기준 {spx_source}) 적용 · "
            f"5pt 구간 · 70% Value Area · 최근 {hours_covered:.1f}시간(정규장+프리/애프터)"
        ),
    }


TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
CVD_WINDOW_HOURS = 24    # 목표 조회 구간
CVD_MAX_BARS = 96        # 화면에 그릴 봉 개수 상한 (촘촘한 타임프레임은 구간이 짧아집니다)


def compute_cvd(es_candles, tf_key, source):
    """봉 색(종가>=시가) 기준 매수/매도 거래량 근사치. 실제 체결 CVD 가 아닙니다.
    최근 CVD_WINDOW_HOURS 시간을 선택한 타임프레임 봉으로 나눠서 보여주되,
    봉 개수가 CVD_MAX_BARS 를 넘으면(촘촘한 타임프레임) 최근 CVD_MAX_BARS 개만 표시합니다."""
    if not es_candles:
        return None
    tf_min = TF_MINUTES.get(tf_key, 60)
    tf_label = TF_LABEL.get(tf_key, tf_key)
    max_by_window = max(1, int(CVD_WINDOW_HOURS * 60 // tf_min))
    n = min(max_by_window, CVD_MAX_BARS, len(es_candles))
    bars = es_candles[-n:]
    if not bars:
        return None

    buy = sell = running = 0.0
    out = []
    for c in bars:
        v = c["v"]
        bull = c["c"] >= c["o"]
        if bull:
            buy += v
            running += v
        else:
            sell += v
            running -= v
        out.append({"t": c["t"], "vol": round(v / 1000.0, 2), "is_bull": bull, "cvd_line": round(running / 1000.0, 2)})
    total = buy + sell
    if total <= 0:
        return None
    buy_pct = int(round(buy / total * 100))
    sell_pct = 100 - buy_pct
    if buy_pct >= 65:
        status, tone = "Buying Pressure", "bull"
        text = f"Strong buying pressure – {buy_pct}% of session volume in bullish bars."
    elif buy_pct >= 55:
        status, tone = "Buying Pressure", "bull"
        text = f"Moderate buying pressure – {buy_pct}% of session volume in bullish bars."
    elif buy_pct > 45:
        status, tone = "Balanced", "flat"
        text = f"Balanced flow – buy {buy_pct}% / sell {sell_pct}% of session volume."
    elif buy_pct > 35:
        status, tone = "Selling Pressure", "bear"
        text = f"Moderate selling pressure – {sell_pct}% of session volume in bearish bars."
    else:
        status, tone = "Selling Pressure", "bear"
        text = f"Strong selling pressure – {sell_pct}% of session volume in bearish bars."

    start_ts, end_ts = bars[0]["t"], bars[-1]["t"]
    covered_hours = (end_ts - start_ts) / 3600.0
    aggregate_range = f"{et_label_sec(start_ts)} ~ {et_label_sec(end_ts)} ({len(bars)}개 {tf_label} 봉)"
    data_desc = (
        f"ES 최근 {covered_hours:.1f}시간 · {source} · ES=F price history · "
        f"봉 색(종가≥시가) 기준 근사치 · 실제 체결(Buy/Sell) CVD 아님"
    )
    return {
        "source": source,
        "data_time": et_label_sec(bars[-1]["t"]),
        "last_bar_time": et_time_sec(bars[-1]["t"]),
        "status": status,
        "tone": tone,
        "aggregate_range": aggregate_range,
        "data_desc": data_desc,
        "buy_pct": buy_pct,
        "sell_pct": sell_pct,
        "buy_vol": fmt_vol(buy),
        "sell_vol": fmt_vol(sell),
        "recent_vol": fmt_vol(bars[-1]["v"]),
        "total_vol": fmt_vol(total),
        "bars": out,
        "summary_text": text,
    }


# ─────────────────────────────────────────────────────────────
# GEX (옵션 체인 기반)
# ─────────────────────────────────────────────────────────────
def bs_gamma(S, K, T, sigma, r=0.0):
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
        g = pdf / (S * sigma * math.sqrt(T))
        return g if math.isfinite(g) else 0.0
    except (ValueError, OverflowError, ZeroDivisionError):
        return 0.0


def _valid_gamma(g):
    g = num(g)
    return g if g is not None and 0.0 < g < 5.0 else None


def _valid_iv(iv):
    iv = num(iv)
    return iv if iv is not None and 0.01 <= iv <= 5.0 else None


def _chain_exps(data):
    if not isinstance(data, dict):
        return []
    keys = set()
    for mkey in ("callExpDateMap", "putExpDateMap"):
        for k in (data.get(mkey) or {}).keys():
            keys.add(k.split(":")[0])
    return sorted(keys)


def parse_schwab_chain(data, exp_date):
    contracts = []
    for side, mkey in (("C", "callExpDateMap"), ("P", "putExpDateMap")):
        for ekey, strikes in (data.get(mkey) or {}).items():
            if ekey.split(":")[0] != exp_date:
                continue
            for skey, arr in (strikes or {}).items():
                for o in arr or []:
                    if not isinstance(o, dict):
                        continue
                    K = num(o.get("strikePrice"))
                    if K is None:
                        K = num(skey)
                    if K is None:
                        continue
                    iv = num(o.get("volatility"))  # Schwab 은 % 단위 (-999 = 없음)
                    contracts.append({
                        "K": K,
                        "side": side,
                        "oi": num(o.get("openInterest")) or 0.0,
                        "iv": _valid_iv(iv / 100.0) if iv is not None else None,
                        "gamma": _valid_gamma(o.get("gamma")),
                        "bid": num(o.get("bid")),
                        "ask": num(o.get("ask")),
                        "last": num(o.get("last")),
                    })
    return contracts


def fetch_schwab_chain(token, today_date):
    """(contracts, exp_date) 또는 None.
    오늘(today_date) 만기(0DTE)를 우선 조회합니다. 단일 날짜로 조회해야
    Schwab 이 그 날짜에 있는 스트라이크를 strikeCount 개수만큼 온전히 돌려줍니다
    (여러 날짜를 한 번에 요청하면 strikeCount 가 만기별로 쪼개져서 0DTE 스트라이크
    해상도가 떨어지고, 그러면 Wall·Gamma Flip·Net GEX 가 다른 사이트와 크게 어긋납니다).
    오늘 조회가 비어 있을 때만(휴장 다음 첫 거래일 등) 기간을 넓혀 재시도합니다."""
    if not token:
        return None

    def ask(from_date, to_date, strike_count):
        return schwab_get(
            token,
            "/chains",
            {
                "symbol": "$SPX",
                "contractType": "ALL",
                "strikeCount": strike_count,
                "includeUnderlyingQuote": "false",
                "fromDate": from_date.isoformat(),
                "toDate": to_date.isoformat(),
            },
            timeout=6,
        )

    today_str = today_date.isoformat()
    data = ask(today_date, today_date, 80)
    exps = _chain_exps(data)
    if today_str not in exps:
        # 오늘 만기가 없었던 경우에만 기간을 넓혀서 가장 가까운 미래 만기를 찾습니다.
        wide = ask(today_date, today_date + timedelta(days=7), 30)
        wide_exps = _chain_exps(wide)
        if wide_exps:
            data, exps = wide, wide_exps
    if not exps:
        return None
    exp = today_str if today_str in exps else exps[0]
    contracts = parse_schwab_chain(data, exp)
    return (contracts, exp) if contracts else None


def fetch_yahoo_chain(start_date):
    """Yahoo SPY 옵션체인 (yfinance). 필요할 때만 import 해서 콜드스타트를 줄입니다."""
    try:
        import yfinance as yf
    except Exception:
        return None
    try:
        t = yf.Ticker("SPY")
        today_str = start_date.isoformat()
        cand = sorted(e for e in list(t.options or []) if e >= today_str)
        if not cand:
            return None
        exp = today_str if today_str in cand else cand[0]
        ch = t.option_chain(exp)
        contracts = []
        for side, df in (("C", ch.calls), ("P", ch.puts)):
            for row in df.to_dict("records"):
                K = num(row.get("strike"))
                if K is None:
                    continue
                contracts.append({
                    "K": K,
                    "side": side,
                    "oi": num(row.get("openInterest")) or 0.0,
                    "iv": _valid_iv(row.get("impliedVolatility")),
                    "gamma": None,
                    "bid": num(row.get("bid")),
                    "ask": num(row.get("ask")),
                    "last": num(row.get("lastPrice")),
                })
        return (contracts, exp) if contracts else None
    except Exception:
        return None


def _mid(c):
    b, a = c.get("bid"), c.get("ask")
    if b and a and b > 0 and a > 0:
        return (b + a) / 2.0
    last = c.get("last")
    return last if last and last > 0 else None


def atm_straddle(contracts, S):
    by_k = {}
    for c in contracts:
        m = _mid(c)
        if m is None:
            continue
        by_k.setdefault(c["K"], {})[c["side"]] = m
    both = {k: v for k, v in by_k.items() if "C" in v and "P" in v}
    if not both:
        return None
    k = min(both, key=lambda x: abs(x - S))
    return both[k]["C"] + both[k]["P"]


def gamma_flip_level(contracts, S, T):
    """스팟을 ±3% 움직여 가며 딜러 순감마(콜 +, 풋 −)가 0 이 되는 지점을 찾습니다."""
    prof = [c for c in contracts if c["iv"] and c["oi"] > 0 and abs(c["K"] / S - 1.0) <= 0.05]
    if len(prof) < 6:
        return None, None
    pts = 41
    grid = [S * (0.97 + 0.06 * i / (pts - 1)) for i in range(pts)]
    vals = []
    for s in grid:
        tot = 0.0
        for c in prof:
            d = bs_gamma(s, c["K"], T, c["iv"]) * c["oi"] * 100.0 * s * s * 0.01
            tot += d if c["side"] == "C" else -d
        vals.append(tot)
    crossings = []
    for i in range(len(grid) - 1):
        a, b = vals[i], vals[i + 1]
        if a == 0:
            crossings.append(grid[i])
        elif a * b < 0:
            crossings.append(grid[i] + (grid[i + 1] - grid[i]) * (a / (a - b)))
    if crossings:
        return min(crossings, key=lambda x: abs(x - S)), None
    return None, ("±3% 범위 안에 전환점 없음 - 전 구간 양(+) 감마" if vals[0] > 0 else "±3% 범위 안에 전환점 없음 - 전 구간 음(−) 감마")


def analyze_gex(contracts, spot, scale, exp_date, now_et, source):
    """contracts 의 행사가는 체인 자체 단위(SPX=1.0, SPY=SPX/SPY 비율)입니다. scale 로 SPX 레벨로 환산."""
    S = spot / scale
    y, m, d = (int(x) for x in exp_date.split("-"))
    exp_dt = ET.localize(datetime(y, m, d, 16, 0))
    secs = (exp_dt - now_et).total_seconds()
    T = max(secs, 300.0) / SECONDS_PER_YEAR

    use = [c for c in contracts if 0.9 * S <= c["K"] <= 1.1 * S and c["oi"] > 0]
    if len(use) < 6:
        return None

    per = {}  # 행사가 -> {call_gex(+$), put_gex(-$), call_oi, put_oi, call_gamma, put_gamma}
    for c in use:
        g = c["gamma"] or (bs_gamma(S, c["K"], T, c["iv"]) if c["iv"] else None)
        e = per.setdefault(c["K"], {"call_gex": 0.0, "put_gex": 0.0, "call_oi": 0.0, "put_oi": 0.0,
                                     "call_gamma": None, "put_gamma": None, "call_iv": None, "put_iv": None})
        if c["side"] == "C":
            e["call_oi"] += c["oi"]
            e["call_iv"] = c["iv"] if e["call_iv"] is None else e["call_iv"]
        else:
            e["put_oi"] += c["oi"]
            e["put_iv"] = c["iv"] if e["put_iv"] is None else e["put_iv"]
        if not g:
            continue
        dg = g * c["oi"] * 100.0 * S * S * 0.01
        if c["side"] == "C":
            e["call_gex"] += dg
            e["call_gamma"] = g
        else:
            e["put_gex"] -= dg
            e["put_gamma"] = g
    if not per:
        return None

    # 벽(Wall) = 미결제약정(OI)이 가장 큰 행사가. 콜은 현재가 이상, 풋은 현재가 이하에서 찾습니다.
    above = [k for k, e in per.items() if k >= S and e["call_oi"] > 0] or [k for k, e in per.items() if e["call_oi"] > 0]
    below = [k for k, e in per.items() if k <= S and e["put_oi"] > 0] or [k for k, e in per.items() if e["put_oi"] > 0]
    call_wall = max(above, key=lambda k: per[k]["call_oi"]) * scale if above else None
    put_wall = max(below, key=lambda k: per[k]["put_oi"]) * scale if below else None

    net_total = sum(e["call_gex"] + e["put_gex"] for e in per.values())
    flip, flip_note = gamma_flip_level(use, S, T)
    straddle = atm_straddle(contracts, S)
    em_pt = straddle * scale if straddle else None

    # 행사가별 세부 내역 (Tradytics 등 다른 사이트와 strike 단위로 직접 대조할 수 있도록 노출합니다)
    nearest = sorted(per.items(), key=lambda kv: abs(kv[0] - S))[:14]
    by_strike = []
    for K, e in sorted(nearest, key=lambda kv: kv[0]):
        net_m = (e["call_gex"] + e["put_gex"]) / 1e6
        by_strike.append({
            "strike": round(K * scale, 1),
            "call_oi": int(e["call_oi"]),
            "put_oi": int(e["put_oi"]),
            "call_iv": round(e["call_iv"] * 100, 1) if e["call_iv"] else None,
            "put_iv": round(e["put_iv"] * 100, 1) if e["put_iv"] else None,
            "call_gamma": round(e["call_gamma"], 5) if e["call_gamma"] else None,
            "put_gamma": round(e["put_gamma"], 5) if e["put_gamma"] else None,
            "call_gex_m": round(e["call_gex"] / 1e6, 1),
            "put_gex_m": round(e["put_gex"] / 1e6, 1),
            "net_gex_m": round(net_m, 1),
        })

    return {
        "available": True,
        "source": source,
        "expiration": exp_date,
        "is_0dte": bool(exp_date == now_et.date().isoformat() and secs > 0),
        "call_wall": round(call_wall, 1) if call_wall is not None else None,
        "put_wall": round(put_wall, 1) if put_wall is not None else None,
        "gamma_flip": round(flip * scale, 1) if flip is not None else None,
        "gamma_flip_note": flip_note,
        "em_pt": round(em_pt, 1) if em_pt else None,
        "expected_move": f"±{em_pt:.1f}pt ({em_pt / spot * 100:.2f}%)" if em_pt else None,
        "net_gex": fmt_dollars(net_total),
        "regime": "positive" if net_total >= 0 else "negative",
        "regime_text": ("양(+) 감마 우세 - 딜러 헤지가 변동성을 누르는 경향" if net_total >= 0
                        else "음(−) 감마 우세 - 딜러 헤지가 움직임을 키우는 경향"),
        "strike_count": len(per),
        "by_strike": by_strike,
    }


def gex_na(reason):
    return {"available": False, "source": "N/A", "reason": reason}


def get_gex(token, spx_p, ratio, now_et):
    if spx_p is None:
        return gex_na("SPX 현재가를 가져오지 못했습니다")
    start = now_et.date() if now_et.hour < 16 else now_et.date() + timedelta(days=1)

    def load():
        r = fetch_schwab_chain(token, start)
        if r:
            res = analyze_gex(r[0], spx_p, 1.0, r[1], now_et, f"{SRC_SCHWAB} 옵션체인 (SPX/SPXW 단일 만기 {r[1]})")
            if res:
                return res
        if ratio:
            r = fetch_yahoo_chain(start)
            if r:
                res = analyze_gex(
                    r[0], spx_p, ratio, r[1], now_et,
                    f"{SRC_YAHOO} SPY 옵션체인 (단일 만기 {r[1]}) x SPX/SPY {ratio:.3f} 환산 · 근사치",
                )
                if res:
                    return res
        return None

    return cached("gex", 20, load) or gex_na("옵션체인을 가져오지 못했습니다 (Schwab · Yahoo 모두 실패)")


# ─────────────────────────────────────────────────────────────
# 방향 분석 (SPX 봉 기반 규칙 계산)
# ─────────────────────────────────────────────────────────────
DIR_WEIGHTS = {"1h": 0.35, "15m": 0.30, "5m": 0.20, "1m": 0.15}


def sgn(x):
    return 1 if x > 0 else (-1 if x < 0 else 0)


def status_of(score):
    if score >= 3.5:
        return "상승 우세", "bull"
    if score >= 1.5:
        return "상승 편향", "bull"
    if score > -1.5:
        return "중립", "flat"
    if score > -3.5:
        return "하락 편향", "bear"
    return "하락 우세", "bear"


def analyze_tf(candles):
    """봉 6가지 신호의 합(-6 ~ +6). 봉이 22개 미만이면 None."""
    closes = [c["c"] for c in candles]
    if len(closes) < 22:
        return None
    e9, e21 = ema_series(closes, 9), ema_series(closes, 21)
    comps = [
        sgn(closes[-1] - e9[-1]),   # 가격 vs EMA9
        sgn(e9[-1] - e21[-1]),      # EMA9 vs EMA21
    ]
    if len(closes) >= 50:
        e50 = ema_series(closes, 50)
        comps.append(sgn(e21[-1] - e50[-1]))  # EMA21 vs EMA50
    else:
        comps.append(0)
    comps.append(sgn(e21[-1] - e21[-4]))      # EMA21 기울기 (3봉)
    rs = rsi_series(closes)
    comps.append(0 if not rs else (1 if rs[-1] >= 55 else (-1 if rs[-1] <= 45 else 0)))
    if len(candles) >= 6:
        h3, h6 = max(c["h"] for c in candles[-3:]), max(c["h"] for c in candles[-6:-3])
        l3, l6 = min(c["l"] for c in candles[-3:]), min(c["l"] for c in candles[-6:-3])
        comps.append(1 if (h3 > h6 and l3 > l6) else (-1 if (h3 < h6 and l3 < l6) else 0))
    else:
        comps.append(0)
    score = sum(comps)
    label, tone = status_of(score)
    return {"score": score, "status": label, "tone": tone}


def build_evidence(spx_p, vwap_val, c1h, rsi_1h):
    ev = []
    if spx_p is not None and vwap_val is not None:
        diff = spx_p - vwap_val
        ev.append({
            "title": "VWAP 위치",
            "signal": "bull" if diff > 0 else ("bear" if diff < 0 else "flat"),
            "text": f"가격이 VWAP {'위' if diff > 0 else ('아래' if diff < 0 else '와 동일')} ({diff:+.2f}pt)",
        })
    else:
        ev.append({"title": "VWAP 위치", "signal": "na", "text": "N/A (SPX 현재가 또는 VWAP 데이터 없음)"})

    if len(c1h) >= 6:
        h3, h6 = max(c["h"] for c in c1h[-3:]), max(c["h"] for c in c1h[-6:-3])
        l3, l6 = min(c["l"] for c in c1h[-3:]), min(c["l"] for c in c1h[-6:-3])
        if h3 > h6 and l3 > l6:
            sig, txt = "bull", "최근 고점과 저점이 함께 높아지는 상승 구조"
        elif h3 < h6 and l3 < l6:
            sig, txt = "bear", "최근 고점과 저점이 함께 낮아지는 하락 구조"
        else:
            sig, txt = "flat", "고점·저점이 엇갈려 뚜렷한 구조가 없음"
        ev.append({"title": "고점·저점 구조", "signal": sig, "text": txt})
    else:
        ev.append({"title": "고점·저점 구조", "signal": "na", "text": "N/A (1H 봉 부족)"})

    if rsi_1h is not None:
        if rsi_1h >= 70:
            sig, txt = "bull", f"RSI {rsi_1h} – 과매수 구간 (상승 모멘텀 강함, 과열 주의)"
        elif rsi_1h >= 55:
            sig, txt = "bull", f"RSI {rsi_1h} – 상승 모멘텀"
        elif rsi_1h <= 30:
            sig, txt = "bear", f"RSI {rsi_1h} – 과매도 구간 (하락 모멘텀 강함, 반등 가능성 주의)"
        elif rsi_1h <= 45:
            sig, txt = "bear", f"RSI {rsi_1h} – 하락 모멘텀"
        else:
            sig, txt = "flat", f"RSI {rsi_1h} – 중립"
        ev.append({"title": "RSI(14)", "signal": sig, "text": txt})
    else:
        ev.append({"title": "RSI(14)", "signal": "na", "text": "N/A (1H 봉 부족)"})

    if len(c1h) >= 4:
        mom = c1h[-1]["c"] - c1h[-4]["c"]
        ev.append({
            "title": "최근 모멘텀",
            "signal": "bull" if mom > 0 else ("bear" if mom < 0 else "flat"),
            "text": f"최근 3개 봉 기준 {'상승' if mom > 0 else ('하락' if mom < 0 else '보합')} ({abs(mom):.2f}pt)",
        })
    else:
        ev.append({"title": "최근 모멘텀", "signal": "na", "text": "N/A (1H 봉 부족)"})
    return ev


def build_direction(tf_results, tf_sources, evidence):
    avail = {k: v for k, v in tf_results.items() if v}
    if not avail:
        return {"available": False, "source": "N/A", "reason": "SPX 봉 데이터를 가져오지 못했습니다"}
    wsum = sum(DIR_WEIGHTS[k] for k in avail)
    score = sum(DIR_WEIGHTS[k] * avail[k]["score"] for k in avail) / wsum
    label, tone = status_of(score)
    match = sum(1 for v in avail.values() if v["tone"] == tone)
    match_pct = int(round(match / len(avail) * 100))

    if tone == "bull":
        summary = f"큰 방향과 장중 흐름이 상승 쪽으로 기울었습니다. {match_pct}%의 시간봉이 상승 또는 상승 편향을 보입니다."
    elif tone == "bear":
        summary = f"큰 방향과 장중 흐름이 하락 쪽으로 기울었습니다. {match_pct}%의 시간봉이 하락 또는 하락 편향을 보입니다."
    else:
        summary = f"시간봉 간 방향이 엇갈려 뚜렷한 우세가 없습니다. {match_pct}%의 시간봉이 중립입니다."
    one_h = avail.get("1h")
    if one_h and one_h["tone"] != tone:
        summary += f" 다만 1H(큰 방향)는 {one_h['status']}입니다."

    kinds = {src_kind(tf_sources.get(k)) for k in avail}
    names = {"schwab": "Charles Schwab", "yahoo": "Yahoo Finance"}
    src = " + ".join(names[x] for x in ("schwab", "yahoo") if x in kinds) or "N/A"
    tfs = {}
    for k in ("1h", "15m", "5m", "1m"):
        v = avail.get(k)
        tfs[k] = {**v, "source": tf_sources.get(k)} if v else None
    return {
        "available": True,
        "score": round(score, 1),
        "score_text": f"{score:+.1f}",
        "status": label,
        "tone": tone,
        "match_pct": match_pct,
        "summary": summary,
        "tfs": tfs,
        "evidence": evidence,
        "source": f"{src} · SPX 봉 EMA(9/21/50)·RSI·고저점 구조 규칙 계산",
    }


# ─────────────────────────────────────────────────────────────
# 금리
# ─────────────────────────────────────────────────────────────
def norm_yield(x):
    """지수 단위가 %×10(예: 42.5) 이든 %(예: 4.25) 이든 % 로 맞춥니다."""
    if x is None:
        return None
    return x / 10.0 if x > 25 else x


# ─────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────
@app.get("/api/market-data")
def get_market_data(vwap_tf: str = "1H", rsi_tf: str = "1H", cvd_tf: str = "15m"):
    now_et = datetime.now(ET)
    now_str = now_et.strftime("%m/%d %H:%M:%S ET")
    errors = []

    def guard(name, fn, *args):
        try:
            return fn(*args)
        except Exception as e:  # 한 블록이 죽어도 나머지는 살립니다
            errors.append(f"{name}: {type(e).__name__}: {e}")
            return None

    token, schwab_msg = get_schwab_token()
    quotes = guard("quotes", get_all_quotes, token) or {}
    q_spx, q_spy = quotes.get("spx"), quotes.get("spy")
    spx_p = q_spx["price"] if q_spx else None
    ratio_q = (spx_p / q_spy["price"]) if (spx_p and q_spy and q_spy["price"]) else None

    v_key, r_key, c_key = normalize_tf(vwap_tf), normalize_tf(rsi_tf), normalize_tf(cvd_tf)
    with ThreadPoolExecutor(max_workers=10) as ex:
        f_spx = {k: ex.submit(get_candles, token, "spx", k) for k in {"1h", "15m", "5m", "1m", r_key}}
        f_spy_v = ex.submit(get_candles, token, "spy", v_key)
        f_es_5 = ex.submit(get_candles, token, "es", "5m")
        f_es = ex.submit(get_candles, token, "es", c_key)
        f_gex = ex.submit(get_gex, token, spx_p, ratio_q, now_et)

    def result(name, fut):
        return guard(name, fut.result)

    spx_c = {k: result(f"candles spx {k}", f) for k, f in f_spx.items()}
    spy_v = result("candles spy vwap", f_spy_v)
    es_5 = result("candles es 5m", f_es_5)
    es_c = result("candles es", f_es)
    gex = result("gex", f_gex) or gex_na("GEX 계산 오류")

    def ratio_for(spy_data):
        if ratio_q:
            return ratio_q
        if spx_p and spy_data and spy_data["candles"]:
            return spx_p / spy_data["candles"][-1]["c"]
        return None

    vwap = guard("vwap", compute_vwap, spy_v["candles"], ratio_for(spy_v), spy_v["source"]) if spy_v else None
    spx_5 = spx_c.get("5m")
    vp = (
        guard("volume_profile", compute_volume_profile, es_5["candles"], spx_5["candles"], es_5["source"], spx_5["source"])
        if es_5 and spx_5 else None
    )
    cvd = guard("cvd", compute_cvd, es_c["candles"], c_key, es_c["source"]) if es_c else None

    rsi = None
    rc = spx_c.get(r_key)
    if rc:
        rs = rsi_series([c["c"] for c in rc["candles"]])
        if rs:
            cur = rs[-1]
            rsi = {
                "val": cur,
                "status": "Overbought" if cur >= 70 else ("Oversold" if cur <= 30 else ("Bullish" if cur >= 55 else ("Bearish" if cur <= 45 else "Neutral"))),
                "history": rs[-20:],
                "source": f"{rc['source']} · Wilder RSI(14)",
            }

    tf_results, tf_sources = {}, {}
    for k in ("1h", "15m", "5m", "1m"):
        d = spx_c.get(k)
        tf_results[k] = guard(f"direction {k}", analyze_tf, d["candles"]) if d else None
        tf_sources[k] = d["source"] if d else None
    c1h = spx_c["1h"]["candles"] if spx_c.get("1h") else []
    rs_1h = rsi_series([c["c"] for c in c1h])
    evidence = build_evidence(spx_p, vwap["val"] if vwap else None, c1h, rs_1h[-1] if rs_1h else None)
    direction = guard("direction", build_direction, tf_results, tf_sources, evidence) or {
        "available": False, "source": "N/A", "reason": "방향 분석 오류"}

    # 금리 (^IRX 는 13주 T-bill 이라 "2Y" 가 아니라 "3M" 으로 표기합니다)
    q10, q30, q3m = quotes.get("tnx"), quotes.get("tyx"), quotes.get("irx")
    y10 = norm_yield(q10["price"]) if q10 else None
    y30 = norm_yield(q30["price"]) if q30 else None
    y3m = norm_yield(q3m["price"]) if q3m else None
    spread_bp = int(round((y10 - y3m) * 100)) if (y10 is not None and y3m is not None) else None

    def pct_text(v):
        return f"{v:.3f}%" if v is not None else None

    yields = {
        "y3m": pct_text(y3m),
        "y10": pct_text(y10),
        "y30": pct_text(y30),
        "spread": (f"{'+' if spread_bp >= 0 else ''}{spread_bp} bp" if spread_bp is not None else None),
        "sources": {
            "y3m": q3m["source"] if q3m else None,
            "y10": q10["source"] if q10 else None,
            "y30": q30["source"] if q30 else None,
        },
    }

    def slim(q):
        return {"price": q["price"], "change": q["change"], "source": q["source"]} if q else None

    # 화면 상단 배지용: 이번 응답에서 실제로 사용된 출처 집계
    used = [q["source"] for q in quotes.values() if q]
    used += [x["source"] for x in (vwap, vp, rsi, cvd) if x]
    used.append(gex.get("source"))
    used += [s for s in tf_sources.values() if s]
    counts = {"schwab": 0, "yahoo": 0, "na": 0}
    for s in used:
        kind = src_kind(s)
        if kind in counts:
            counts[kind] += 1
    missing = sum(1 for k in QUOTES if not quotes.get(k))
    summary = f"Schwab {counts['schwab']} · Yahoo {counts['yahoo']}" + (f" · N/A {missing}" if missing else "")

    status_msg = schwab_msg
    if token and q_spx and src_kind(q_spx["source"]) == "yahoo":
        status_msg += " · 단, 시세 응답이 없어 Yahoo 로 대체됨"

    return {
        "status": "success",
        "timestamp": now_str,
        "source": summary,
        "source_summary": summary,
        "schwab_status": status_msg,
        "errors": errors,
        "spx": q_spx,
        "es": quotes.get("es"),
        "vix": slim(quotes.get("vix")),
        "vix9d": slim(quotes.get("vix9d")),
        "mag7": quotes.get("mag7"),
        "yields": yields,
        "volume_profile": vp,
        "vwap": vwap,
        "gex": gex,
        "rsi": rsi,
        "cvd": cvd,
        "direction": direction,
    }
