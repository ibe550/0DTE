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

import html as html_lib
from typing import Optional

import pytz
import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

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
# 영속 저장소 (Vercel KV / Upstash Redis REST API)
# ─────────────────────────────────────────────────────────────
def _kv_config():
    url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        return None, None
    return url.rstrip("/"), token


def kv_cmd(*args):
    url, token = _kv_config()
    if not url:
        return None
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=list(args),
            timeout=4,
        )
        if r.status_code == 200:
            return r.json().get("result")
    except Exception:
        pass
    return None


def kv_get(key):
    return kv_cmd("GET", key)


def kv_set(key, value, ex_seconds=None):
    if ex_seconds:
        return kv_cmd("SET", key, value, "EX", str(int(ex_seconds))) is not None
    return kv_cmd("SET", key, value) is not None


KV_AVAILABLE = _kv_config()[0] is not None


# ─────────────────────────────────────────────────────────────
# Schwab 인증 / 호출
# ─────────────────────────────────────────────────────────────
_TOKEN = {"value": None, "exp": 0.0}
SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
KV_KEY_ACCESS = "schwab:access_token"
KV_KEY_ACCESS_EXP = "schwab:access_token_exp"
KV_KEY_REFRESH = "schwab:refresh_token"
REFRESH_TOKEN_TTL = 8 * 24 * 3600


def _schwab_token_request(data, app_key, app_secret):
    try:
        res = requests.post(
            SCHWAB_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data,
            auth=(app_key, app_secret) if app_secret else None,
            timeout=6,
        )
    except Exception as e:
        return None, f"Schwab 토큰 요청 오류 ({type(e).__name__})"
    if res.status_code == 200:
        try:
            return res.json(), None
        except Exception:
            return None, "Schwab 응답 파싱 실패"
    hint = ""
    if res.status_code in (400, 401):
        hint = " - refresh token 만료(7일) 또는 키/시크릿 확인. /api/callback 으로 재인증하세요"
    return None, f"Schwab 토큰 갱신 실패 (HTTP {res.status_code}){hint}"


def get_schwab_token(force_refresh=False):
    now = time.time()
    if not force_refresh and _TOKEN["value"] and now < _TOKEN["exp"]:
        return _TOKEN["value"], "연결됨 (캐시)"

    app_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_SECRET")
    if not app_key:
        return None, "Schwab 환경변수 없음 (SCHWAB_APP_KEY)"

    if not force_refresh:
        kv_exp = num(kv_get(KV_KEY_ACCESS_EXP))
        if kv_exp and now < kv_exp - 30:
            kv_access = kv_get(KV_KEY_ACCESS)
            if kv_access:
                _TOKEN["value"] = kv_access
                _TOKEN["exp"] = kv_exp - 30
                return kv_access, "연결됨 (공유 캐시)"

    refresh_token = kv_get(KV_KEY_REFRESH) or os.environ.get("SCHWAB_REFRESH_TOKEN")
    if not refresh_token:
        return None, "refresh_token 없음 - /api/callback 으로 최초 인증이 필요합니다"

    body, err = _schwab_token_request({"grant_type": "refresh_token", "refresh_token": refresh_token}, app_key, app_secret)
    if not body:
        return None, err

    access_token = body.get("access_token")
    new_refresh = body.get("refresh_token")
    if not access_token:
        return None, "Schwab 응답에 access_token 이 없습니다"
    ttl = int(num(body.get("expires_in")) or 1800)

    _TOKEN["value"] = access_token
    _TOKEN["exp"] = now + max(60, ttl - 120)
    if KV_AVAILABLE:
        kv_set(KV_KEY_ACCESS, access_token, ex_seconds=ttl)
        kv_set(KV_KEY_ACCESS_EXP, str(now + ttl), ex_seconds=ttl)
        if new_refresh:
            kv_set(KV_KEY_REFRESH, new_refresh, ex_seconds=REFRESH_TOKEN_TTL)

    return access_token, "연결됨 (새로 갱신)"


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
            _TOKEN["value"] = None
            if KV_AVAILABLE:
                kv_set(KV_KEY_ACCESS_EXP, "0")
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────
# 시세 (Schwab 우선 -> Yahoo)
# ─────────────────────────────────────────────────────────────
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
    ("wti", ("/CL", "CL=F")),
    ("brent", ("/BZ", "BZ=F")),
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
# 주요 경제 지표 캘린더 (PCE, CPI, GDP, FOMC, 고용 종합 - ET 전용)
# ─────────────────────────────────────────────────────────────
ECON_TITLE_KR = {
    "Core PCE Price Index m/m": "근원 PCE 물가지수 (MoM)",
    "Core PCE Price Index y/y": "근원 PCE 물가지수 (YoY)",
    "PCE Price Index m/m": "PCE 물가지수 (MoM)",
    "PCE Price Index y/y": "PCE 물가지수 (YoY)",
    "CPI m/m": "소비자물가지수 (CPI MoM)",
    "CPI y/y": "소비자물가지수 (CPI YoY)",
    "Core CPI m/m": "근원 CPI (MoM)",
    "Core CPI y/y": "근원 CPI (YoY)",
    "PPI m/m": "생산자물가지수 (PPI MoM)",
    "Core PPI m/m": "근원 PPI (MoM)",
    "Non-Farm Employment Change": "비농업 고용지수 (NFP)",
    "Unemployment Rate": "실업률",
    "Unemployment Claims": "신규 실업수당 청구건수",
    "Advance GDP q/q": "GDP 성장률 (속보치)",
    "Prelim GDP q/q": "GDP 성장률 (잠정치)",
    "Final GDP q/q": "GDP 성장률 (확정치)",
    "FOMC Statement": "FOMC 성명서 발표",
    "Federal Funds Rate": "연준 기준금리 결정",
    "FOMC Press Conference": "파월 의장 기자회견",
    "FOMC Meeting Minutes": "FOMC 회의록 공개",
    "ISM Manufacturing PMI": "ISM 제조업 PMI",
    "ISM Services PMI": "ISM 서비스업 PMI",
    "JOLTS Job Openings": "JOLTS 구인건수",
    "Retail Sales m/m": "소매판매 (MoM)",
    "Core Retail Sales m/m": "근원 소매판매 (MoM)",
    "Prelim UoM Consumer Sentiment": "미시간대 소비자심리지수 (예비치)",
    "Revised UoM Consumer Sentiment": "미시간대 소비자심리지수 (확정치)",
}

HIGH_IMPACT_KEYWORDS = [
    "pce", "cpi", "ppi", "employment", "non-farm", "unemployment", "claims",
    "gdp", "fomc", "fed ", "federal funds", "powell", "ism", "jolts",
    "retail sales", "consumer sentiment"
]


def fetch_global_econ_calendar():
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=4.5)
        if r.status_code != 200:
            return None
        data = r.json()
        parsed = []
        for it in data:
            if it.get("country") != "USD":
                continue
            title = (it.get("title") or "").strip()
            impact = it.get("impact", "")
            t_lower = title.lower()

            is_target = (impact == "High") or any(k in t_lower for k in HIGH_IMPACT_KEYWORDS)
            if not is_target:
                continue

            raw_date = it.get("date", "")
            if not raw_date:
                continue

            try:
                dt_obj = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).astimezone(ET)
            except Exception:
                continue

            kr_name = ECON_TITLE_KR.get(title, title)
            parsed.append({
                "title": kr_name,
                "title_en": title,
                "dt": dt_obj,
                "ts": dt_obj.timestamp(),
                "time": dt_obj.strftime("%H:%M ET"),
                "impact": impact
            })
        return parsed
    except Exception:
        return None


def get_today_econ_events(now_et):
    events = cached("econ_events_data", 900, fetch_global_econ_calendar)
    now_ts = now_et.timestamp()

    if not events:
        return {"items": [], "source": "N/A", "error": "경제 캘린더를 가져오지 못했습니다"}

    today = now_et.date()
    tomorrow = today + timedelta(days=1)

    today_items = [e for e in events if e["dt"].date() == today]
    target_items = today_items

    is_tomorrow = False
    if not today_items and now_et.hour >= 16:
        tomorrow_items = [e for e in events if e["dt"].date() == tomorrow]
        if tomorrow_items:
            target_items = tomorrow_items
            is_tomorrow = True

    target_items.sort(key=lambda x: x["ts"])

    out_items = []
    for it in target_items:
        passed = (it["ts"] <= now_ts)
        prefix = f"[{it['dt'].strftime('%m/%d')}] " if is_tomorrow else ""
        out_items.append({
            "title": f"{prefix}{it['title']}",
            "title_en": it["title_en"],
            "time": it["time"],
            "ts": it["ts"],
            "passed": passed,
            "impact": it.get("impact", "High")
        })

    return {
        "items": out_items,
        "source": "공식 경제 캘린더 (PCE·CPI·FOMC·고용 종합 · ET 전용)",
        "error": None
    }


# ─────────────────────────────────────────────────────────────
# 봉(candle) 데이터 (Schwab pricehistory 우선 -> Yahoo chart)
# ─────────────────────────────────────────────────────────────
TF_SPEC = {
    "1m": ("1m", "5d", 1, 5, None),
    "5m": ("5m", "5d", 5, 5, None),
    "10m": ("5m", "5d", 5, 5, 10),
    "15m": ("15m", "5d", 15, 5, None),
    "30m": ("30m", "5d", 30, 5, None),
    "1h": ("60m", "1mo", 30, 10, 60),
}
TF_LABEL = {"1m": "1m", "5m": "5m", "10m": "10m", "15m": "15m", "30m": "30m", "1h": "1H"}
TF_MINUTES = {"1m": 1, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60}
INSTR = {"spx": ("$SPX", "^GSPC"), "spy": ("SPY", "SPY"), "es": (None, "ES=F")}


def normalize_tf(tf):
    key = str(tf or "").strip().lower()
    return key if key in TF_SPEC else "10m"


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
            continue
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
            if agg:
                cs = aggregate_candles(cs, agg)
            return {"candles": cs, "source": f"{SRC_YAHOO} ({ysym} {TF_LABEL[key]})"}
        return None

    return cached(f"candles:{inst}:{key}", 10 if key in ("1m", "5m", "10m") else 30, load)


def get_rth_session(candles, now_et=None):
    if not candles:
        return [], False, None

    if now_et is None:
        now_et = datetime.now(ET)

    today = now_et.date()
    is_rth_or_after = (now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30))

    sessions_by_date = OrderedDict()
    for c in candles:
        dt = datetime.fromtimestamp(c["t"], ET)
        d = dt.date()
        d_open = int(ET.localize(datetime(d.year, d.month, d.day, 9, 30, 0)).timestamp())
        d_close = int(ET.localize(datetime(d.year, d.month, d.day, 16, 0, 0)).timestamp())
        if d_open <= c["t"] <= d_close:
            if d not in sessions_by_date:
                sessions_by_date[d] = []
            sessions_by_date[d].append(c)

    if not sessions_by_date:
        return [], False, None

    all_dates = sorted(sessions_by_date.keys())

    if is_rth_or_after and today in sessions_by_date and sessions_by_date[today]:
        return sessions_by_date[today], False, today.strftime("%m/%d")

    prior_dates = [d for d in all_dates if d < today]
    if prior_dates:
        target_date = prior_dates[-1]
        return sessions_by_date[target_date], True, target_date.strftime("%m/%d")

    target_date = all_dates[-1]
    is_prior = (target_date < today) or (target_date == today and not is_rth_or_after)
    return sessions_by_date[target_date], is_prior, target_date.strftime("%m/%d")


def et_label(ts):
    return datetime.fromtimestamp(ts, ET).strftime("%m/%d %H:%M ET")


def et_label_sec(ts):
    return datetime.fromtimestamp(ts, ET).strftime("%m/%d %H:%M:%S ET")


def et_time_sec(ts):
    return datetime.fromtimestamp(ts, ET).strftime("%H:%M:%S ET")


def fmt_vol(v):
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
# 긴급 위험 감지 (Crash / Flash Sell-Off / Put Wall Breakdown Alert)
# ─────────────────────────────────────────────────────────────
def detect_market_risk(spx_p, spy_5m_candles, ratio, gex, cvd, vix_q, now_et):
    """단기 급락, 풋월/감마플립 붕괴, CVD 매도 덤핑, VIX 급등을 종합 감시합니다."""
    if not spx_p:
        return {"active": False}

    reasons = []
    level = "NORMAL"

    # 1. 단기 급락 속도 체크 (5분봉 및 15분 누적 하락폭)
    if spy_5m_candles and len(spy_5m_candles) >= 1 and ratio:
        last_c = spy_5m_candles[-1]
        # 직전 5분봉 하락폭 (SPX 환산)
        bar_5m_drop = (last_c["c"] - last_c["o"]) * ratio
        bar_5m_drop_pct = ((last_c["c"] - last_c["o"]) / last_c["o"]) * 100

        if bar_5m_drop <= -12.0 or bar_5m_drop_pct <= -0.22:
            reasons.append(f"최근 5분간 SPX {bar_5m_drop:.1f}pt ({bar_5m_drop_pct:.2f}%) 단기 급락 발생")
            level = "CRITICAL"

        if len(spy_5m_candles) >= 3:
            drop_15m = (spy_5m_candles[-1]["c"] - spy_5m_candles[-3]["o"]) * ratio
            drop_15m_pct = ((spy_5m_candles[-1]["c"] - spy_5m_candles[-3]["o"]) / spy_5m_candles[-3]["o"]) * 100
            if drop_15m <= -25.0 or drop_15m_pct <= -0.40:
                reasons.append(f"최근 15분간 누적 {drop_15m:.1f}pt ({drop_15m_pct:.2f}%) 가속 하락 중")
                level = "CRITICAL"

    # 2. GEX 핵심 방어선 붕괴 체크
    if gex and gex.get("available"):
        pw = gex.get("put_wall")
        flip = gex.get("gamma_flip")

        if pw and spx_p < pw:
            diff = spx_p - pw
            reasons.append(f"Put Wall 지지선({pw:.1f}) 하향 붕괴 이탈 ({diff:.1f}pt) - 딜러 방어선 무너짐")
            level = "CRITICAL"
        elif pw and (spx_p - pw) <= 6.0:
            reasons.append(f"Put Wall 최대 지지선({pw:.1f}) 붕괴 임박 (현재가와 {spx_p - pw:.1f}pt 차이)")
            if level != "CRITICAL":
                level = "WARNING"

        if flip and spx_p < flip:
            reasons.append(f"Gamma Flip({flip:.1f}) 하회: 음(−) 감마 가속화 구간 진입 (변동성 증폭 위험)")
            if level != "CRITICAL":
                level = "WARNING"

    # 3. CVD 패닉 매도 덤핑 체크
    if cvd and cvd.get("sell_pct"):
        sell_pct = cvd["sell_pct"]
        if sell_pct >= 65 and cvd.get("tone") == "bear":
            reasons.append(f"시장가 매도 압도적 폭발 (Sell 볼륨 {sell_pct}%, {cvd.get('sell_vol')})")
            if level != "CRITICAL":
                level = "WARNING"

    # 4. VIX 급등 체크
    if vix_q:
        vix_p = vix_q.get("price")
        vix_pct = vix_q.get("change_pct")
        if vix_pct and vix_pct >= 5.0:
            reasons.append(f"VIX 공포지수 급등세 (+{vix_pct:.1f}%, {vix_p:.2f})")
            if level != "CRITICAL":
                level = "WARNING"

    is_active = len(reasons) > 0
    title = "🚨 [위험감지] 시장 급락 및 딜러 방어선 붕괴 경보" if level == "CRITICAL" else "⚠️ [위험감지] 하방 변동성 및 매도 압력 주의보"

    return {
        "active": is_active,
        "level": level,
        "title": title,
        "details": reasons,
        "timestamp": now_et.strftime("%H:%M:%S ET")
    }


# ─────────────────────────────────────────────────────────────
# VWAP / Volume Profile / CVD
# ─────────────────────────────────────────────────────────────
def compute_vwap(spy_candles, ratio, source, now_et=None):
    sess, is_prior, sess_date = get_rth_session(spy_candles, now_et)
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
    prefix = f"[전일({sess_date}) 마감 · 09:30 ET 리셋] " if is_prior else ""
    return {
        "val": series[-1],
        "sigma": round(sd, 2),
        "series": series,
        "upper1": u1,
        "lower1": l1,
        "upper2": u2,
        "lower2": l2,
        "data_time": et_label(sess[-1]["t"]),
        "is_prior": is_prior,
        "source": f"{source} x SPX/SPY 환산 · {prefix}{sess_date} 정규장 VWAP · 밴드=거래량가중 표준편차",
    }


def compute_volume_profile(spy_candles, ratio, source, now_et=None):
    sess, is_prior, sess_date = get_rth_session(spy_candles, now_et)
    if not sess or not ratio:
        return None

    bins = {}
    total = 0.0

    for c in sess:
        v = c["v"]
        if v <= 0:
            continue

        lo = c["l"] * ratio
        hi = c["h"] * ratio
        op = c["o"] * ratio
        cl = c["c"] * ratio

        if hi < lo:
            lo, hi = hi, lo

        lo_b = int(round(lo / 5.0)) * 5
        hi_b = int(round(hi / 5.0)) * 5
        rng = list(range(lo_b, hi_b + 5, 5))
        if not rng:
            continue

        body_lo = min(op, cl)
        body_hi = max(op, cl)

        weights = []
        for b in rng:
            if body_lo - 2.5 <= b <= body_hi + 2.5:
                weights.append(2.5)
            else:
                weights.append(1.0)

        w_sum = sum(weights)
        for b, w in zip(rng, weights):
            each = v * (w / w_sum)
            bins[b] = bins.get(b, 0.0) + each
            total += each

    if not bins or total <= 0:
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

    start_ts, end_ts = sess[0]["t"], sess[-1]["t"]
    hours_covered = (end_ts - start_ts) / 3600.0
    prefix = f"[전일({sess_date}) 마감 · 09:30 ET 리셋] " if is_prior else ""

    return {
        "val": float(keys[lo_i]),
        "poc": float(poc),
        "vah": float(keys[hi_i]),
        "hours_covered": round(hours_covered, 1),
        "is_prior": is_prior,
        "source": (
            f"{source} x SPX/SPY 환산 · {prefix}{sess_date} 정규장 (09:30~{et_time_sec(end_ts)}) · "
            f"5pt 구간 · 70% Value Area · 몸통 가중치 프로파일"
        ),
    }


def compute_cvd(candles, tf_key, source, symbol="SPY", now_et=None):
    if not candles:
        return None
    tf_label = TF_LABEL.get(tf_key, tf_key)

    bars, is_prior, sess_date = get_rth_session(candles, now_et)
    if not bars:
        return None

    buy = sell = running = 0.0
    out = []
    for c in bars:
        v = c["v"]
        h, l, cl = c["h"], c["l"], c["c"]
        rng = h - l

        if rng > 0:
            buy_ratio = (cl - l) / rng
            sell_ratio = (h - cl) / rng
        else:
            buy_ratio = 0.5
            sell_ratio = 0.5

        bar_buy = v * buy_ratio
        bar_sell = v * sell_ratio
        bar_delta = bar_buy - bar_sell

        buy += bar_buy
        sell += bar_sell
        running += bar_delta

        out.append({
            "t": c["t"],
            "vol": round(v / 1000.0, 2),
            "is_bull": bar_delta >= 0,
            "cvd_line": round(running / 1000.0, 2),
        })

    total = buy + sell
    if total <= 0:
        return None

    buy_pct = int(round(buy / total * 100))
    sell_pct = 100 - buy_pct

    if buy_pct >= 60:
        status, tone = "Buying Pressure", "bull"
        text = f"Strong buying pressure – {buy_pct}% buy volume in session."
    elif buy_pct >= 53:
        status, tone = "Buying Pressure", "bull"
        text = f"Moderate buying pressure – {buy_pct}% buy volume in session."
    elif buy_pct > 47:
        status, tone = "Balanced", "flat"
        text = f"Balanced flow – buy {buy_pct}% / sell {sell_pct}% in session."
    elif buy_pct > 40:
        status, tone = "Selling Pressure", "bear"
        text = f"Moderate selling pressure – {sell_pct}% sell volume in session."
    else:
        status, tone = "Selling Pressure", "bear"
        text = f"Strong selling pressure – {sell_pct}% sell volume in session."

    start_ts, end_ts = bars[0]["t"], bars[-1]["t"]
    if is_prior:
        aggregate_range = f"{sess_date} 전일 정규장 (09:30 ~ {et_time_sec(end_ts)}) · {len(bars)}개 {tf_label} 봉 · [09:30 ET 자동 리셋]"
        status_suffix = " (전일 마감)"
    else:
        aggregate_range = f"{sess_date} 정규장 (09:30 ~ {et_time_sec(end_ts)}) · {len(bars)}개 {tf_label} 봉"
        status_suffix = ""

    prefix = f"[전일({sess_date}) 마감 · 09:30 ET 리셋] " if is_prior else ""
    data_desc = (
        f"{symbol} {prefix}정규장(09:30~) · {source} · "
        f"A/D 체결 압력(고저-종가 가중) 기반 정밀 CVD"
    )
    return {
        "source": f"{source} {'· [전일 마감 기준]' if is_prior else ''}",
        "data_time": et_label_sec(bars[-1]["t"]),
        "last_bar_time": et_time_sec(bars[-1]["t"]),
        "is_prior": is_prior,
        "session_date": sess_date,
        "status": f"{status}{status_suffix}",
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
        "summary_text": text + (" (※ 09:30 ET 개장 전으로 전일 정규장 마감 데이터가 표시 중입니다)" if is_prior else ""),
    }


# ─────────────────────────────────────────────────────────────
# GEX (0DTE 최적화: SPX/SPXW 실시간 Volume+OI 결합 & 진짜 Gamma Wall)
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
                    iv = num(o.get("volatility"))
                    oi = num(o.get("openInterest")) or 0.0
                    vol = num(o.get("totalVolume")) or num(o.get("volume")) or 0.0
                    contracts.append({
                        "K": K,
                        "side": side,
                        "oi": oi,
                        "vol": vol,
                        "iv": _valid_iv(iv / 100.0) if iv is not None else None,
                        "gamma": _valid_gamma(o.get("gamma")),
                        "bid": num(o.get("bid")),
                        "ask": num(o.get("ask")),
                        "last": num(o.get("last")),
                    })
    return contracts


def fetch_schwab_chain(token, today_date):
    if not token:
        return None, {"reason": "토큰 없음"}

    def ask(sym, from_date, to_date, strike_count):
        return schwab_get(
            token,
            "/chains",
            {
                "symbol": sym,
                "contractType": "ALL",
                "strikeCount": strike_count,
                "includeUnderlyingQuote": "false",
                "fromDate": from_date.isoformat(),
                "toDate": to_date.isoformat(),
            },
            timeout=6,
        )

    today_str = today_date.isoformat()
    data = ask("$SPX", today_date, today_date, 160)
    exps = _chain_exps(data)
    used_sym = "$SPX"

    if today_str not in exps:
        data_spxw = ask("$SPXW", today_date, today_date, 160)
        exps_spxw = _chain_exps(data_spxw)
        if today_str in exps_spxw:
            data = data_spxw
            exps = exps_spxw
            used_sym = "$SPXW"

    single_day_had_today = today_str in exps
    widened = False
    if not single_day_had_today:
        widened = True
        wide = ask("$SPX", today_date, today_date + timedelta(days=7), 40)
        wide_exps = _chain_exps(wide)
        if wide_exps:
            data, exps = wide, wide_exps

    diag = {
        "requested_date": today_str,
        "single_day_query_had_today": single_day_had_today,
        "used_symbol": used_sym,
        "widened_to_7d": widened,
        "all_expirations_seen": exps[:10],
    }
    if not exps:
        return None, diag

    exp = today_str if today_str in exps else exps[0]
    contracts = parse_schwab_chain(data, exp)
    return (contracts, exp) if contracts else None, diag


def fetch_yahoo_chain(start_date):
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
                    "vol": num(row.get("volume")) or 0.0,
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
    prof = [c for c in contracts if c["iv"] and (c["oi"] > 0 or c.get("vol", 0) > 0) and abs(c["K"] / S - 1.0) <= 0.06]
    if len(prof) < 6:
        return None, None
    pts = 61
    grid = [S * (0.96 + 0.08 * i / (pts - 1)) for i in range(pts)]
    vals = []
    for s in grid:
        tot = 0.0
        for c in prof:
            eff_qty = max(c["oi"], c.get("vol", 0.0))
            d = bs_gamma(s, c["K"], T, c["iv"]) * eff_qty * 100.0 * s * s * 0.01
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
    return None, ("전 구간 양(+) 감마 우세" if vals[0] > 0 else "전 구간 음(−) 감마 우세")


def analyze_gex(contracts, spot, scale, exp_date, now_et, source, diag=None):
    S = spot / scale
    y, m, d = (int(x) for x in exp_date.split("-"))
    exp_dt = ET.localize(datetime(y, m, d, 16, 0))
    secs = (exp_dt - now_et).total_seconds()

    T = max(secs, 1800.0) / SECONDS_PER_YEAR

    use = [c for c in contracts if 0.88 * S <= c["K"] <= 1.12 * S and (c["oi"] > 0 or c.get("vol", 0) > 0)]
    if len(use) < 6:
        return None

    per = {}
    gamma_from_schwab = gamma_from_calc = 0
    for c in use:
        raw_g = c["gamma"]
        g = raw_g or (bs_gamma(S, c["K"], T, c["iv"]) if c["iv"] else None)
        if g:
            gamma_from_schwab += 1 if raw_g else 0
            gamma_from_calc += 0 if raw_g else 1

        e = per.setdefault(c["K"], {
            "call_gex": 0.0, "put_gex": 0.0,
            "call_oi": 0.0, "put_oi": 0.0,
            "call_vol": 0.0, "put_vol": 0.0,
            "call_gamma": None, "put_gamma": None,
            "call_iv": None, "put_iv": None
        })

        eff_qty = max(c["oi"], c.get("vol", 0.0))

        if c["side"] == "C":
            e["call_oi"] += c["oi"]
            e["call_vol"] += c.get("vol", 0.0)
            e["call_iv"] = c["iv"] if e["call_iv"] is None else e["call_iv"]
        else:
            e["put_oi"] += c["oi"]
            e["put_vol"] += c.get("vol", 0.0)
            e["put_iv"] = c["iv"] if e["put_iv"] is None else e["put_iv"]

        if not g or eff_qty <= 0:
            continue

        dg = g * eff_qty * 100.0 * S * S * 0.01
        if c["side"] == "C":
            e["call_gex"] += dg
            e["call_gamma"] = g
        else:
            e["put_gex"] -= dg
            e["put_gamma"] = g

    if not per:
        return None

    gamma_source_note = (
        f"감마 {gamma_from_schwab}개는 Schwab 제공값, {gamma_from_calc}개는 BS 실시간 계산값"
        if (gamma_from_schwab or gamma_from_calc) else None
    )

    calls_with_gex = [k for k, e in per.items() if e["call_gex"] > 0]
    puts_with_gex = [k for k, e in per.items() if e["put_gex"] < 0]

    call_wall = max(calls_with_gex, key=lambda k: per[k]["call_gex"]) * scale if calls_with_gex else None
    put_wall = min(puts_with_gex, key=lambda k: per[k]["put_gex"]) * scale if puts_with_gex else None

    net_total = sum(e["call_gex"] + e["put_gex"] for e in per.values())
    flip, flip_note = gamma_flip_level(use, S, T)
    straddle = atm_straddle(contracts, S)
    em_pt = straddle * scale if straddle else None

    nearest = sorted(per.items(), key=lambda kv: abs(kv[0] - S))[:14]
    by_strike = []
    for K, e in sorted(nearest, key=lambda kv: kv[0]):
        net_m = (e["call_gex"] + e["put_gex"]) / 1e6
        by_strike.append({
            "strike": round(K * scale, 1),
            "call_oi": int(e["call_oi"]),
            "put_oi": int(e["put_oi"]),
            "call_vol": int(e["call_vol"]),
            "put_vol": int(e["put_vol"]),
            "call_iv": round(e["call_iv"] * 100, 1) if e["call_iv"] else None,
            "put_iv": round(e["put_iv"] * 100, 1) if e["put_iv"] else None,
            "call_gamma": round(e["call_gamma"], 5) if e["call_gamma"] else None,
            "put_gamma": round(e["put_gamma"], 5) if e["put_gamma"] else None,
            "call_gex_m": round(e["call_gex"] / 1e6, 1),
            "put_gex_m": round(e["put_gex"] / 1e6, 1),
            "net_gex_m": round(net_m, 1),
        })

    oi_above_call = sum(e["call_oi"] for k, e in per.items() if k >= S)
    oi_above_put = sum(e["put_oi"] for k, e in per.items() if k >= S)
    oi_below_call = sum(e["call_oi"] for k, e in per.items() if k < S)
    oi_below_put = sum(e["put_oi"] for k, e in per.items() if k < S)

    target_date = now_et.date() if now_et.hour < 16 else (now_et.date() + timedelta(days=1))
    is_0dte_session = bool(
        (now_et.hour < 16 and exp_date == now_et.date().isoformat() and secs > 0) or
        (now_et.hour >= 16 and exp_date >= target_date.isoformat())
    )

    return {
        "available": True,
        "source": source,
        "expiration": exp_date,
        "is_0dte": is_0dte_session,
        "call_wall": round(call_wall, 1) if call_wall is not None else None,
        "put_wall": round(put_wall, 1) if put_wall is not None else None,
        "gamma_flip": round(flip * scale, 1) if flip is not None else None,
        "gamma_flip_note": flip_note,
        "em_pt": round(em_pt, 1) if em_pt else None,
        "expected_move": f"±{em_pt:.1f}pt ({em_pt / spot * 100:.2f}%)" if em_pt else None,
        "net_gex": fmt_dollars(net_total),
        "regime": "positive" if net_total >= 0 else "negative",
        "regime_text": ("양(+) 감마 우세 - 딜러 헤지가 변동성을 누르는 구간" if net_total >= 0
                        else "음(−) 감마 우세 - 딜러 헤지가 변동성을 증폭시키는 구간"),
        "strike_count": len(per),
        "by_strike": by_strike,
        "gamma_source_note": gamma_source_note,
        "oi_skew": {
            "call_oi_at_or_above_spot": int(oi_above_call),
            "put_oi_at_or_above_spot": int(oi_above_put),
            "call_oi_below_spot": int(oi_below_call),
            "put_oi_below_spot": int(oi_below_put),
        },
        "chain_diag": diag,
    }


def gex_na(reason, diag=None):
    return {"available": False, "source": "N/A", "reason": reason, "chain_diag": diag}


def get_gex(token, spx_p, ratio, now_et):
    if spx_p is None:
        return gex_na("SPX 현재가를 가져오지 못했습니다")
    start = now_et.date() if now_et.hour < 16 else now_et.date() + timedelta(days=1)

    def load():
        r, diag = fetch_schwab_chain(token, start)
        if r:
            sym_tag = diag.get("used_symbol", "$SPX")
            res = analyze_gex(r[0], spx_p, 1.0, r[1], now_et, f"{SRC_SCHWAB} {sym_tag} 체인 (실시간 Volume+OI 결합 GEX)", diag)
            if res:
                return res
        if ratio:
            ry = fetch_yahoo_chain(start)
            if ry:
                res = analyze_gex(
                    ry[0], spx_p, ratio, ry[1], now_et,
                    f"{SRC_YAHOO} SPY 체인 (단일 만기 {ry[1]}) x SPX/SPY 환산 · 근사치",
                    diag,
                )
                if res:
                    return res
        return gex_na("옵션체인을 가져오지 못했습니다 (Schwab · Yahoo 모두 실패)", diag)

    return cached("gex", 15, load) or gex_na("옵션체인을 가져오지 못했습니다 (Schwab · Yahoo 모두 실패)")


# ─────────────────────────────────────────────────────────────
# 방향 분석 (0DTE 최적화: 초단타 EMA 5/13/21 + 캔들 모멘텀 + VWAP/CVD 연동)
# ─────────────────────────────────────────────────────────────
DIR_WEIGHTS = {"5m": 0.35, "1m": 0.25, "15m": 0.25, "1h": 0.15}


def status_of(score):
    if score >= 3.0:
        return "상승 우세", "bull"
    if score >= 1.2:
        return "상승 편향", "bull"
    if score > -1.2:
        return "중립", "flat"
    if score > -3.0:
        return "하락 편향", "bear"
    return "하락 우세", "bear"


def analyze_tf(candles):
    closes = [c["c"] for c in candles]
    if len(closes) < 15:
        return None
    e5 = ema_series(closes, 5)
    e13 = ema_series(closes, 13)
    e21 = ema_series(closes, 21)

    p_vs_e5 = 1.0 if closes[-1] > e5[-1] else -1.0
    e5_vs_e13 = 1.0 if e5[-1] > e13[-1] else -1.0
    e13_vs_e21 = 1.0 if e13[-1] > e21[-1] else -1.0

    e5_slope = 1.0 if (len(e5) >= 2 and e5[-1] > e5[-2]) else -1.0

    last_c = candles[-1]
    rng = last_c["h"] - last_c["l"]
    body = last_c["c"] - last_c["o"]
    bar_imp = 0.0
    if rng > 0:
        if body < 0 and (last_c["h"] - last_c["c"]) / rng >= 0.75:
            bar_imp = -1.5
        elif body > 0 and (last_c["c"] - last_c["l"]) / rng >= 0.75:
            bar_imp = 1.5
        else:
            bar_imp = 0.5 if body > 0 else -0.5

    rs = rsi_series(closes, period=9)
    rsi_val = rs[-1] if rs else 50.0
    rsi_score = 1.0 if rsi_val >= 55 else (-1.0 if rsi_val <= 45 else 0.0)

    raw_score = p_vs_e5 + e5_vs_e13 + e13_vs_e21 + e5_slope + bar_imp + rsi_score
    score = max(-6.0, min(6.0, raw_score))
    label, tone = status_of(score)
    return {"score": round(score, 1), "status": label, "tone": tone}


def build_evidence(spx_p, vwap_val, c1h, rsi_1h, cvd_data):
    ev = []
    if spx_p is not None and vwap_val is not None:
        diff = spx_p - vwap_val
        ev.append({
            "title": "VWAP 위치",
            "signal": "bull" if diff > 0 else ("bear" if diff < 0 else "flat"),
            "text": f"현재가가 당일 VWAP {'위' if diff > 0 else ('아래' if diff < 0 else '와 동일')} ({diff:+.2f}pt)",
        })
    else:
        ev.append({"title": "VWAP 위치", "signal": "na", "text": "N/A (VWAP 데이터 없음)"})

    if cvd_data:
        ev.append({
            "title": "CVD 볼륨 압력",
            "signal": cvd_data["tone"],
            "text": f"{cvd_data['status']} (Buy {cvd_data['buy_pct']}% / Sell {cvd_data['sell_pct']}%)",
        })
    else:
        ev.append({"title": "CVD 볼륨 압력", "signal": "na", "text": "N/A"})

    if len(c1h) >= 6:
        h3, h6 = max(c["h"] for c1h_bar in c1h[-3:] for c in [c1h_bar]), max(c["h"] for c1h_bar in c1h[-6:-3] for c in [c1h_bar])
        l3, l6 = min(c["l"] for c1h_bar in c1h[-3:] for c in [c1h_bar]), min(c["l"] for c1h_bar in c1h[-6:-3] for c in [c1h_bar])
        if h3 > h6 and l3 > l6:
            sig, txt = "bull", "최근 고점과 저점이 함께 높아지는 상승 구조"
        elif h3 < h6 and l3 < l6:
            sig, txt = "bear", "최근 고점과 저점이 함께 낮아지는 하락 구조"
        else:
            sig, txt = "flat", "고점·저점이 엇갈려 뚜렷한 구조가 없음"
        ev.append({"title": "상위(1H) 구조", "signal": sig, "text": txt})
    else:
        ev.append({"title": "상위(1H) 구조", "signal": "na", "text": "N/A"})

    if len(c1h) >= 3:
        mom = c1h[-1]["c"] - c1h[-3]["c"]
        ev.append({
            "title": "단기 모멘텀",
            "signal": "bull" if mom > 0 else ("bear" if mom < 0 else "flat"),
            "text": f"최근 2개 봉 기준 {'상승' if mom > 0 else ('하락' if mom < 0 else '보합')} ({abs(mom):.2f}pt)",
        })
    return ev


def build_direction(tf_results, tf_sources, evidence, vwap_diff=None, cvd_data=None):
    avail = {k: v for k, v in tf_results.items() if v}
    if not avail:
        return {"available": False, "source": "N/A", "reason": "SPY 실시간 봉 데이터를 가져오지 못했습니다"}

    wsum = sum(DIR_WEIGHTS[k] for k in avail)
    raw_score = sum(DIR_WEIGHTS[k] * avail[k]["score"] for k in avail) / wsum

    score = raw_score
    if vwap_diff is not None:
        if vwap_diff < -1.0:
            score -= 1.5
        elif vwap_diff > 1.0:
            score += 1.0

    if cvd_data:
        if cvd_data.get("tone") == "bear":
            score -= 1.5
        elif cvd_data.get("tone") == "bull":
            score += 1.0

    score = max(-6.0, min(6.0, score))
    label, tone = status_of(score)
    match = sum(1 for v in avail.values() if v["tone"] == tone)
    match_pct = int(round(match / len(avail) * 100))

    if tone == "bull":
        summary = f"단기 모멘텀과 체결 압력이 상승 쪽으로 기울었습니다. {match_pct}%의 시간봉이 상승 편향을 보입니다."
    elif tone == "bear":
        summary = f"단기 모멘텀과 매도 덤핑 압력이 우세합니다. {match_pct}%의 시간봉이 하락 편향을 보입니다."
    else:
        summary = f"시간봉 및 VWAP 간 방향이 엇갈려 박스권 중립 흐름입니다."

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
        "source": f"{src} (SPY 실시간) · 0DTE EMA(5/13/21)·VWAP·CVD 결합 판정",
    }


# ─────────────────────────────────────────────────────────────
# 금리
# ─────────────────────────────────────────────────────────────
def yield_scale(raw_price):
    if raw_price is None:
        return 1.0
    return 10.0 if raw_price > 25 else 1.0


def norm_yield(x, scale=None):
    if x is None:
        return None
    s = scale if scale is not None else yield_scale(x)
    return x / s


# ─────────────────────────────────────────────────────────────
# API 엔드포인트
# ─────────────────────────────────────────────────────────────
@app.get("/api/market-data")
def get_market_data(vwap_tf: str = "1H", rsi_tf: str = "1H", cvd_tf: str = "10m"):
    now_et = datetime.now(ET)
    now_str = now_et.strftime("%m/%d %H:%M:%S ET")
    errors = []

    def guard(name, fn, *args):
        try:
            return fn(*args)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
            return None

    token, schwab_msg = get_schwab_token()
    quotes = guard("quotes", get_all_quotes, token) or {}
    q_spx, q_spy = quotes.get("spx"), quotes.get("spy")
    spx_p = q_spx["price"] if q_spx else None
    ratio_q = (spx_p / q_spy["price"]) if (spx_p and q_spy and q_spy["price"]) else None

    v_key, r_key, c_key = normalize_tf(vwap_tf), normalize_tf(rsi_tf), normalize_tf(cvd_tf)
    with ThreadPoolExecutor(max_workers=9) as ex:
        f_spy_dir = {k: ex.submit(get_candles, token, "spy", k) for k in {"1h", "15m", "5m", "1m"}}
        f_spx_r = ex.submit(get_candles, token, "spx", r_key)
        f_spy_v = ex.submit(get_candles, token, "spy", v_key)
        f_spy_c = ex.submit(get_candles, token, "spy", c_key)
        f_gex = ex.submit(get_gex, token, spx_p, ratio_q, now_et)
        f_econ = ex.submit(get_today_econ_events, now_et)

    def result(name, fut):
        return guard(name, fut.result)

    spy_dir_c = {k: result(f"candles spy dir {k}", f) for k, f in f_spy_dir.items()}
    spx_r = result("candles spx rsi", f_spx_r)
    spy_v = result("candles spy vwap", f_spy_v)
    spy_c = result("candles spy cvd", f_spy_c)
    gex = result("gex", f_gex) or gex_na("GEX 계산 오류")
    econ_events = result("econ_events", f_econ) or {"items": [], "source": "N/A", "error": "계산 오류"}

    def ratio_for(spy_data):
        if ratio_q:
            return ratio_q
        if spx_p and spy_data and spy_data["candles"]:
            return spx_p / spy_data["candles"][-1]["c"]
        return None

    # 1. VWAP (개장 전 전일 마감 세션 유지 / 09:30 자동 리셋)
    vwap = guard("vwap", compute_vwap, spy_v["candles"], ratio_for(spy_v), spy_v["source"], now_et) if spy_v else None

    # 2. Volume Profile (개장 전 전일 마감 세션 유지 / 09:30 자동 리셋)
    spy_vp = spy_dir_c.get("5m")
    vp = (
        guard("volume_profile", compute_volume_profile, spy_vp["candles"], ratio_for(spy_vp), spy_vp["source"], now_et)
        if (spy_vp and ratio_for(spy_vp)) else None
    )

    # 3. CVD (개장 전 전일 마감 세션 유지 / 09:30 자동 리셋)
    cvd = guard("cvd", compute_cvd, spy_c["candles"], c_key, spy_c["source"], "SPY", now_et) if spy_c else None

    # 4. RSI 계산
    rsi = None
    if spx_r:
        rs = rsi_series([c["c"] for c in spx_r["candles"]])
        if rs:
            cur = rs[-1]
            rsi = {
                "val": cur,
                "status": "Overbought" if cur >= 70 else ("Oversold" if cur <= 30 else ("Bullish" if cur >= 55 else ("Bearish" if cur <= 45 else "Neutral"))),
                "history": rs[-20:],
                "source": f"{spx_r['source']} · Wilder RSI(14)",
            }

    # 5. 실시간 방향 분석 계산
    tf_results, tf_sources = {}, {}
    for k in ("1h", "15m", "5m", "1m"):
        d = spy_dir_c.get(k)
        tf_results[k] = guard(f"direction {k}", analyze_tf, d["candles"]) if d else None
        tf_sources[k] = d["source"] if d else None

    c1h = spy_dir_c["1h"]["candles"] if spy_dir_c.get("1h") else []
    rs_1h = rsi_series([c["c"] for c in c1h])
    vwap_diff = (spx_p - vwap["val"]) if (spx_p and vwap and vwap.get("val")) else None
    evidence = build_evidence(spx_p, vwap["val"] if vwap else None, c1h, rs_1h[-1] if rs_1h else None, cvd)

    direction = guard("direction", build_direction, tf_results, tf_sources, evidence, vwap_diff, cvd) or {
        "available": False, "source": "N/A", "reason": "방향 분석 오류"}

    # 6. 시장 급락 및 위험 감지 시스템
    spy_5m_bars = spy_dir_c.get("5m", {}).get("candles") if spy_dir_c.get("5m") else []
    risk_alert = guard("risk_alert", detect_market_risk, spx_p, spy_5m_bars, ratio_for(spy_vp), gex, cvd, quotes.get("vix"), now_et) or {"active": False}

    # 7. 국채 금리 계산
    q10, q30, q3m = quotes.get("tnx"), quotes.get("tyx"), quotes.get("irx")

    def yield_level_and_change(q):
        if not q:
            return None, None
        scale = yield_scale(q["price"])
        level = norm_yield(q["price"], scale)
        chg = q.get("change")
        bp = int(round(norm_yield(chg, scale) * 100)) if chg is not None else None
        return level, bp

    y10, y10_bp = yield_level_and_change(q10)
    y30, y30_bp = yield_level_and_change(q30)
    y3m, y3m_bp = yield_level_and_change(q3m)
    spread_bp = int(round((y10 - y3m) * 100)) if (y10 is not None and y3m is not None) else None

    def pct_text(v):
        return f"{v:.3f}%" if v is not None else None

    def bp_text(v):
        return f"{'+' if v > 0 else ''}{v} bp" if v is not None else None

    yields = {
        "y3m": pct_text(y3m),
        "y10": pct_text(y10),
        "y30": pct_text(y30),
        "y3m_change_bp": y3m_bp,
        "y10_change_bp": y10_bp,
        "y30_change_bp": y30_bp,
        "y3m_change_text": bp_text(y3m_bp),
        "y10_change_text": bp_text(y10_bp),
        "y30_change_text": bp_text(y30_bp),
        "spread": (f"{'+' if spread_bp > 0 else ''}{spread_bp} bp" if spread_bp is not None else None),
        "sources": {
            "y3m": q3m["source"] if q3m else None,
            "y10": q10["source"] if q10 else None,
            "y30": q30["source"] if q30 else None,
        },
    }

    def slim(q):
        return {"price": q["price"], "change": q["change"], "source": q["source"]} if q else None

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
        "risk_alert": risk_alert,
        "spx": q_spx,
        "es": quotes.get("es"),
        "vix": slim(quotes.get("vix")),
        "vix9d": slim(quotes.get("vix9d")),
        "mag7": quotes.get("mag7"),
        "econ_events": econ_events,
        "wti": quotes.get("wti"),
        "brent": quotes.get("brent"),
        "yields": yields,
        "volume_profile": vp,
        "vwap": vwap,
        "gex": gex,
        "rsi": rsi,
        "cvd": cvd,
        "direction": direction,
    }


# ─────────────────────────────────────────────────────────────
# Schwab OAuth 콜백 (/api/callback)
# ─────────────────────────────────────────────────────────────
def render_callback_page(title, body_html, ok=True):
    color = "#10b981" if ok else "#f43f5e"
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_lib.escape(title)}</title>
<style>
body{{background:#080d1a;color:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;padding:24px;}}
.card{{max-width:640px;margin:0 auto;background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:20px;}}
h1{{font-size:16px;color:{color};margin:0 0 12px;}}
.box{{background:#020617;border:1px solid #1e293b;border-radius:6px;padding:10px;font-family:monospace;
     font-size:12px;word-break:break-all;user-select:all;margin:8px 0;}}
button{{background:#4f46e5;color:#fff;border:none;padding:8px 14px;border-radius:6px;font-size:12px;cursor:pointer;}}
button:active{{background:#4338ca;}}
p{{font-size:12px;color:#94a3b8;line-height:1.7;}}
code{{background:#1e293b;padding:1px 5px;border-radius:4px;}}
</style></head>
<body><div class="card"><h1>{html_lib.escape(title)}</h1>{body_html}</div></body></html>"""


@app.get("/api/callback", response_class=HTMLResponse)
def schwab_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    if error:
        return HTMLResponse(
            render_callback_page("Schwab 인증 실패", f"<p>Schwab 이 인증을 거부했습니다: {html_lib.escape(error)}</p>", ok=False),
            status_code=400,
        )
    if not code:
        return HTMLResponse(
            render_callback_page(
                "잘못된 요청", "<p><code>code</code> 파라미터가 없습니다. Schwab 인증 페이지에서 승인 절차를 다시 시작해주세요.</p>", ok=False
            ),
            status_code=400,
        )

    app_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_SECRET")
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI") or str(request.url).split("?")[0]
    if not app_key or not app_secret:
        return HTMLResponse(
            render_callback_page(
                "설정 오류",
                "<p><code>SCHWAB_APP_KEY</code> / <code>SCHWAB_SECRET</code> 환경변수가 설정되어 있지 않습니다. "
                "Vercel 프로젝트 설정에서 먼저 등록해주세요.</p>",
                ok=False,
            ),
            status_code=500,
        )

    try:
        res = requests.post(
            "https://api.schwabapi.com/v1/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
            auth=(app_key, app_secret),
            timeout=8,
        )
    except Exception as e:
        return HTMLResponse(
            render_callback_page("토큰 교환 실패", f"<p>Schwab 서버 요청 중 오류가 발생했습니다: {html_lib.escape(str(e))}</p>", ok=False),
            status_code=502,
        )

    if res.status_code != 200:
        detail = html_lib.escape(res.text[:500])
        return HTMLResponse(
            render_callback_page(
                "토큰 교환 실패",
                f"<p>Schwab 이 HTTP {res.status_code} 를 반환했습니다. 인가 코드는 보통 30초~몇 분 안에만 유효하니 "
                f"이미 만료됐거나, redirect_uri 가 앱 등록 값과 다를 수 있습니다.</p>"
                f"<div class='box'>{detail}</div>"
                f"<p>이번에 사용된 redirect_uri: <code>{html_lib.escape(redirect_uri)}</code></p>",
                ok=False,
            ),
            status_code=400,
        )

    body = res.json()
    refresh_token = body.get("refresh_token", "")
    access_token = body.get("access_token", "")
    expires_in = body.get("expires_in", "")

    kv_note = ""
    if KV_AVAILABLE:
        now = time.time()
        ttl = int(num(expires_in) or 1800)
        ok_r = kv_set(KV_KEY_REFRESH, refresh_token, ex_seconds=REFRESH_TOKEN_TTL) if refresh_token else False
        ok_a = kv_set(KV_KEY_ACCESS, access_token, ex_seconds=ttl) if access_token else False
        kv_set(KV_KEY_ACCESS_EXP, str(now + ttl), ex_seconds=ttl)
        _TOKEN["value"] = access_token
        _TOKEN["exp"] = now + max(60, ttl - 120)
        if ok_r and ok_a:
            kv_note = (
                "<p style='color:#10b981;'>✅ 저장소(KV)에도 자동으로 반영했습니다 - "
                "Vercel 환경변수를 직접 바꾸지 않으셔도 앱이 바로 이 토큰을 씁니다. "
                "이후로는 앱이 매번 새 refresh_token 을 스스로 저장소에 갱신해두므로, "
                "정상적으로 계속 동작하는 한 다시 로그인하지 않아도 됩니다.</p>"
            )
        else:
            kv_note = "<p style='color:#f59e0b;'>⚠ 저장소(KV) 저장에 실패했습니다. 아래 값을 환경변수에 직접 넣어주세요.</p>"

    manual_note = "" if (KV_AVAILABLE and kv_note.startswith("<p style='color:#10b981")) else (
        "<p>아래 <b>refresh_token</b>을 복사해서 Vercel 프로젝트 설정 → Environment Variables 의 "
        "<code>SCHWAB_REFRESH_TOKEN</code>에 붙여넣고 재배포하세요.</p>"
    )

    return HTMLResponse(render_callback_page(
        "✅ Schwab 인증 성공",
        f"""
        {kv_note}
        {manual_note}
        <div class="box" id="rt">{html_lib.escape(refresh_token)}</div>
        <button onclick="navigator.clipboard.writeText(document.getElementById('rt').innerText).then(()=>{{this.innerText='복사됨 ✓';}})">
            Refresh Token 복사
        </button>
        <p style="margin-top:16px;">access_token 은 참고용입니다 (보통 30분만 유효, 따로 저장할 필요 없음 - 앱이 자동으로 갱신합니다):</p>
        <div class="box" style="color:#64748b;">{html_lib.escape(access_token[:40])}... (expires_in: {html_lib.escape(str(expires_in))}초)</div>
        <p style="margin-top:16px;color:#f59e0b;">⚠ 이 페이지의 값은 계정 접근 권한이 담긴 민감한 정보입니다. 캡처해서 공유하지 마세요.</p>
        """,
    ))


# ─────────────────────────────────────────────────────────────
# 자동 갱신용 크론 엔드포인트 (/api/refresh-token)
# ─────────────────────────────────────────────────────────────
@app.get("/api/refresh-token")
def refresh_token_cron():
    if not KV_AVAILABLE:
        return {"status": "skipped", "reason": "KV 저장소가 연결되어 있지 않습니다 (KV_REST_API_URL/TOKEN 필요)"}
    token, msg = get_schwab_token(force_refresh=True)
    return {"status": "ok" if token else "error", "message": msg}
