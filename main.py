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
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _parse_val(s):
    if not s or not isinstance(s, str):
        return None
    cleaned = s.replace("%", "").replace("K", "").replace("M", "").replace("B", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


_CACHE = {}


def cached(key, ttl, fn):
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
# 텔레그램 실시간 다중 알림 시스템 (10분 쿨다운 탑재)
# ─────────────────────────────────────────────────────────────
_LAST_TELEGRAM_SHOCK = {"ts": 0.0, "type": None}
TELEGRAM_COOLDOWN_SEC = 600


def send_telegram_shock_alert(shock_alert, spx_price, force_test=False):
    if not shock_alert or (not shock_alert.get("active") and not force_test):
        return {"status": "skipped", "reason": "알림 비활성 상태"}
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_ids_raw = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_ids_raw:
        return {"status": "error", "reason": "환경변수 누락"}

    now_ts = time.time()
    s_type = shock_alert.get("type")

    if not force_test:
        if now_ts - _LAST_TELEGRAM_SHOCK["ts"] < TELEGRAM_COOLDOWN_SEC and _LAST_TELEGRAM_SHOCK["type"] == s_type:
            return {"status": "skipped", "reason": "10분 쿨다운 중"}

    _LAST_TELEGRAM_SHOCK["ts"] = now_ts
    _LAST_TELEGRAM_SHOCK["type"] = s_type

    title = shock_alert.get("title", "⚡ [변동성 쇼크]")
    time_info = shock_alert.get("elapsed_text") or shock_alert.get("timestamp") or ""
    details_str = "\n".join(f"• {d}" for d in shock_alert.get("details", []))
    price_str = f"{spx_price:.2f}" if spx_price else "N/A"

    msg = (
        f"{title}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📍 SPX 현재가: {price_str}\n"
        f"⏱ 발생 시각: {time_info}\n"
        f"\n"
        f"🔍 상세 감지 내역:\n"
        f"{details_str}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"SPX 0DTE DEFENDER Realtime Alert"
    )

    chat_ids = [cid.strip() for cid in chat_ids_raw.split(",") if cid.strip()]
    results = []
    for cid in chat_ids:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": msg},
                timeout=4,
            )
            results.append({"chat_id": cid, "ok": r.status_code == 200})
        except Exception as e:
            results.append({"chat_id": cid, "error": str(e)})

    return {"status": "sent", "results": results}


# ─────────────────────────────────────────────────────────────
# 영속 저장소 (Vercel KV / Upstash Redis)
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
# Schwab 인증
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
    hint = " - /api/callback 으로 재인증하세요" if res.status_code in (400, 401) else ""
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
        return None, "refresh_token 없음 - /api/callback 으로 최초 인증 필요"

    body, err = _schwab_token_request({"grant_type": "refresh_token", "refresh_token": refresh_token}, app_key, app_secret)
    if not body:
        return None, err

    access_token = body.get("access_token")
    new_refresh = body.get("refresh_token")
    if not access_token:
        return None, "Schwab 응답에 access_token 없음"
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
# 시세 (VIX1D 탑재 + VIX9D 제거)
# ─────────────────────────────────────────────────────────────
QUOTES = OrderedDict([
    ("spx", ("$SPX", "^GSPC")),
    ("es", ("/ES", "ES=F")),
    ("vix1d", ("$VIX1D", "^VIX1D")),
    ("vix", ("$VIX", "^VIX")),
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
# 주요 경제 지표 캘린더
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


def evaluate_econ_result(title_en, actual_str, forecast_str, previous_str):
    if not actual_str:
        if forecast_str:
            return {"tag": None, "tone": "pending", "sentence": f"시장 예상치: {forecast_str}" + (f" (이전: {previous_str})" if previous_str else "")}
        return {"tag": None, "tone": "pending", "sentence": f"이전치: {previous_str}" if previous_str else "발표 대기중"}

    act_num = _parse_val(actual_str)
    fc_num = _parse_val(forecast_str) if forecast_str else _parse_val(previous_str)
    cmp_label = "예상" if forecast_str else "이전"
    cmp_str = forecast_str or previous_str

    t_lower = title_en.lower()
    is_inflation = any(k in t_lower for k in ["cpi", "pce", "ppi", "price index"])
    is_unemployment = any(k in t_lower for k in ["unemployment rate", "unemployment claims", "jobless claims"])

    if act_num is not None and fc_num is not None:
        diff = act_num - fc_num
        if abs(diff) < 1e-5:
            return {"tag": "⚪ 예상 부합 (중립)", "tone": "flat", "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 시장 예상치 부합"}
        if is_inflation:
            if diff > 0:
                return {"tag": "🔴 물가 과열 (부정적)", "tone": "bear", "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 인플레 우려 (악재)"}
            return {"tag": "🟢 물가 둔화 (긍정적)", "tone": "bull", "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 인플레이션 둔화 (호재)"}
        elif is_unemployment:
            if diff > 0:
                return {"tag": "⚠️ 실업 증가 (부정적)", "tone": "bear", "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 실업 증가 (악재)"}
            return {"tag": "🟢 고용 견조 (긍정적)", "tone": "bull", "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 고용 시장 안정 (호재)"}
        else:
            if diff > 0:
                return {"tag": "🟢 경기 호조 (긍정적)", "tone": "bull", "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 경기 확장 (호재)"}
            return {"tag": "⚠️ 경기 둔화 (부정적)", "tone": "bear", "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 경기 위축 (악재)"}

    return {"tag": "발표 완료", "tone": "flat", "sentence": f"발표치: {actual_str}" + (f" ({cmp_label}: {cmp_str})" if cmp_str else "")}


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
            if not ((impact == "High") or any(k in t_lower for k in HIGH_IMPACT_KEYWORDS)):
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
                "title": kr_name, "title_en": title, "dt": dt_obj, "ts": dt_obj.timestamp(),
                "time": dt_obj.strftime("%H:%M ET"), "impact": impact,
                "forecast": (it.get("forecast") or "").strip(), "previous": (it.get("previous") or "").strip(),
                "actual": (it.get("actual") or "").strip()
            })
        return parsed
    except Exception:
        return None


def get_today_econ_events(now_et):
    events = cached("econ_events_data", 900, fetch_global_econ_calendar)
    now_ts = now_et.timestamp()
    if not events:
        return {"items": [], "source": "N/A", "error": "경제 캘린더 조회 실패"}

    today = now_et.date()
    tomorrow = today + timedelta(days=1)
    today_items = [e for e in events if e["dt"].date() == today]
    active_today_items = [e for e in today_items if (e["ts"] > now_ts) or (now_ts - e["ts"] <= 3600)]

    target_items = active_today_items
    is_tomorrow = False
    if not active_today_items and now_et.hour >= 16:
        tomorrow_items = [e for e in events if e["dt"].date() == tomorrow]
        if tomorrow_items:
            target_items = tomorrow_items
            is_tomorrow = True

    target_items.sort(key=lambda x: x["ts"])
    out_items = []
    for it in target_items:
        passed = (it["ts"] <= now_ts)
        prefix = f"[{it['dt'].strftime('%m/%d')}] " if is_tomorrow else ""
        eval_res = evaluate_econ_result(it["title_en"], it["actual"], it["forecast"], it["previous"])
        out_items.append({
            "title": f"{prefix}{it['title']}", "title_en": it["title_en"], "time": it["time"],
            "ts": it["ts"], "passed": passed, "impact": it.get("impact", "High"),
            "actual": it["actual"], "forecast": it["forecast"], "previous": it["previous"],
            "eval_tag": eval_res["tag"], "eval_tone": eval_res["tone"], "eval_sentence": eval_res["sentence"],
        })

    return {"items": out_items, "source": "공식 경제 캘린더 (PCE·CPI·FOMC·고용 종합 · ET 전용)", "error": None}


# ─────────────────────────────────────────────────────────────
# 봉(candle) 데이터
# ─────────────────────────────────────────────────────────────
TF_SPEC = {
    "1m": ("1m", "2d", 1, 2, None), "5m": ("5m", "5d", 5, 5, None), "10m": ("5m", "5d", 5, 5, 10),
    "15m": ("5m", "5d", 5, 5, 15), "30m": ("5m", "5d", 5, 5, 30), "1h": ("60m", "1mo", 30, 10, 60),
}
TF_LABEL = {"1m": "1m", "5m": "5m", "10m": "10m", "15m": "15m", "30m": "30m", "1h": "1H"}
INSTR = {"spx": ("$SPX", "^GSPC"), "spy": ("SPY", "SPY"), "es": (None, "ES=F")}


def normalize_tf(tf):
    key = str(tf or "").strip().lower()
    return key if key in TF_SPEC else "10m"


def yahoo_candles(symbol, interval, range_str):
    chart = fetch_yahoo_chart(symbol, interval, range_str)
    ts = chart.get("timestamp") or []
    quote = ((chart.get("indicators") or {}).get("quote") or [{}])[0] or {}
    opens, highs, lows, closes, vols = quote.get("open") or [], quote.get("high") or [], quote.get("low") or [], quote.get("close") or [], quote.get("volume") or []
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
    now_ms = int(time.time() * 1000)
    data = schwab_get(
        token, "/pricehistory",
        {"symbol": symbol, "periodType": "day", "period": days, "frequencyType": "minute", "frequency": freq, "endDate": now_ms, "needExtendedHoursData": "true"},
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
        now_et = datetime.now(ET)
        today = now_et.date()
        is_rth = (now_et.weekday() < 5) and ((now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)) and now_et.hour < 16)

        if token and ssym:
            cs = schwab_candles(token, ssym, s_freq, s_days)
            if cs:
                has_today = any(datetime.fromtimestamp(c["t"], ET).date() == today for c in cs)
                if not is_rth or has_today:
                    if agg:
                        cs = aggregate_candles(cs, agg)
                    return {"candles": cs, "source": f"{SRC_SCHWAB} ({ssym} {TF_LABEL[key]})"}

        cs = yahoo_candles(ysym, y_int, y_rng)
        if cs:
            if agg:
                cs = aggregate_candles(cs, agg)
            return {"candles": cs, "source": f"{SRC_YAHOO} ({ysym} {TF_LABEL[key]})"}
        return None

    return cached(f"candles:{inst}:{key}", 6 if key in ("1m", "5m", "10m") else 20, load)


def get_rth_session(candles, now_et=None):
    if not candles:
        return [], False, None
    if now_et is None:
        now_et = datetime.now(ET)
    today = now_et.date()
    is_weekday = (now_et.weekday() < 5)
    is_rth = is_weekday and ((now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)) and now_et.hour < 16)
    is_after_market = is_weekday and (now_et.hour >= 16)

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

    all_dates = sorted(sessions_by_date.keys())
    if is_rth:
        return sessions_by_date.get(today, []), False, today.strftime("%m/%d")
    if is_after_market and today in sessions_by_date:
        return sessions_by_date[today], False, today.strftime("%m/%d")
    prior_dates = [d for d in all_dates if d < today]
    if prior_dates:
        target_date = prior_dates[-1]
        return sessions_by_date[target_date], True, target_date.strftime("%m/%d")
    if all_dates:
        target_date = all_dates[-1]
        return sessions_by_date[target_date], (target_date != today), target_date.strftime("%m/%d")
    return [], False, today.strftime("%m/%d")


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
# 실시간 변동성 쇼크 감지 (VIX1D 우선 감지 탑재)
# ─────────────────────────────────────────────────────────────
def detect_market_shock(spx_p, spy_5m_candles, ratio, gex, cvd, vix_active, now_et):
    if not spx_p:
        return {"active": False}

    today = now_et.date()
    is_weekday = (now_et.weekday() < 5)
    is_rth = is_weekday and ((now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)) and now_et.hour < 16)
    if not is_rth:
        return {"active": False}

    today_open_ts = int(ET.localize(datetime(today.year, today.month, today.day, 9, 30, 0)).timestamp())
    today_bars = [c for c in (spy_5m_candles or []) if c["t"] >= today_open_ts]
    recent_bars = today_bars[-6:] if len(today_bars) >= 2 else []

    reasons = []
    shock_type = "NORMAL"
    level = "NORMAL"
    start_time_label = None
    elapsed_text = ""

    if recent_bars and ratio:
        high_bar = max(recent_bars, key=lambda b: b["h"])
        low_bar = min(recent_bars, key=lambda b: b["l"])
        max_h = high_bar["h"] * ratio
        min_l = low_bar["l"] * ratio
        curr_c = recent_bars[-1]["c"] * ratio

        drop_from_high = curr_c - max_h
        drop_from_high_pct = (drop_from_high / max_h) * 100
        rally_from_low = curr_c - min_l
        rally_from_low_pct = (rally_from_low / min_l) * 100

        if drop_from_high <= -14.0 or drop_from_high_pct <= -0.25:
            start_ts = high_bar["t"]
            elapsed_min = int(max((now_et.timestamp() - start_ts) // 60, 1))
            if elapsed_min <= 30:
                shock_type = "DROP"
                level = "CRITICAL" if (drop_from_high <= -24.0 or drop_from_high_pct <= -0.40) else "WARNING"
                start_dt = datetime.fromtimestamp(start_ts, ET)
                start_time_label = start_dt.strftime("%H:%M ET")
                elapsed_text = f"{start_time_label} 시작 ({elapsed_min}분 경과)"
                reasons.append(f"{start_time_label}부터 {drop_from_high:.1f}pt ({drop_from_high_pct:.2f}%) 단기 급락 발생")

        elif rally_from_low >= 14.0 or rally_from_low_pct >= 0.25:
            start_ts = low_bar["t"]
            elapsed_min = int(max((now_et.timestamp() - start_ts) // 60, 1))
            if elapsed_min <= 30:
                shock_type = "SURGE"
                level = "CRITICAL" if (rally_from_low >= 24.0 or rally_from_low_pct >= 0.40) else "WARNING"
                start_dt = datetime.fromtimestamp(start_ts, ET)
                start_time_label = start_dt.strftime("%H:%M ET")
                elapsed_text = f"{start_time_label} 시작 ({elapsed_min}분 경과)"
                reasons.append(f"{start_time_label}부터 +{rally_from_low:.1f}pt (+{rally_from_low_pct:.2f}%) 단기 급등 발생")

    if gex and gex.get("available") and gex.get("is_0dte"):
        pw, cw, flip = gex.get("put_wall"), gex.get("call_wall"), gex.get("gamma_flip")
        if pw and spx_p < pw:
            reasons.append(f"Put Wall 지지선({pw:.1f}) 하향 붕괴 이탈 ({spx_p - pw:.1f}pt) - 딜러 방어선 파괴")
            if shock_type == "NORMAL":
                shock_type = "DROP"
            level = "CRITICAL"
        if cw and spx_p > cw:
            reasons.append(f"Call Wall 저항선({cw:.1f}) 상향 돌파 (+{spx_p - cw:.1f}pt) - 숏스퀴즈 가속화")
            if shock_type == "NORMAL":
                shock_type = "SURGE"
            level = "CRITICAL"

    if cvd and not cvd.get("is_prior") and cvd.get("sell_pct"):
        if cvd["sell_pct"] >= 65 and cvd.get("tone") == "bear" and shock_type == "DROP":
            reasons.append(f"기관 매도 덤핑 폭발 (Sell {cvd['sell_pct']}%, {cvd.get('sell_vol')})")
        elif cvd["buy_pct"] >= 65 and cvd.get("tone") == "bull" and shock_type == "SURGE":
            reasons.append(f"기관 매수 스퀴즈 유입 (Buy {cvd['buy_pct']}%, {cvd.get('buy_vol')})")

    if vix_active and shock_type == "DROP":
        vix_pct = vix_active.get("change_pct")
        if vix_pct and vix_pct >= 6.0:
            reasons.append(f"0DTE 변동성(VIX1D) 스파이크 폭등 (+{vix_pct:.1f}%, {vix_active.get('price'):.2f})")

    is_active = len(reasons) > 0 and (shock_type in ("DROP", "SURGE"))
    title = "🚨 [변동성 쇼크 · 급락 경보]" if shock_type == "DROP" and level == "CRITICAL" else ("⚠️️ [변동성 쇼크 · 하방 주의보]" if shock_type == "DROP" else ("🚀 [변동성 쇼크 · 급등 경보]" if level == "CRITICAL" else "⚡ [변동성 쇼크 · 상방 모멘텀]"))

    return {
        "active": is_active, "type": shock_type, "level": level, "title": title,
        "start_time": start_time_label, "elapsed_text": elapsed_text, "details": reasons,
        "timestamp": now_et.strftime("%H:%M:%S ET")
    }


# ─────────────────────────────────────────────────────────────
# VWAP (내부 계산 전용) / Volume Profile / CVD
# ─────────────────────────────────────────────────────────────
def compute_vwap(spy_candles, ratio, now_et=None):
    sess, _, _ = get_rth_session(spy_candles, now_et)
    if not sess or not ratio:
        return None
    cum_v = cum_tp = 0.0
    val = None
    for c in sess:
        v = c["v"]
        if v <= 0:
            continue
        tp = (c["h"] + c["l"] + c["c"]) / 3.0 * ratio
        cum_v += v
        cum_tp += tp * v
        val = cum_tp / cum_v
    return {"val": round(val, 2)} if val else None


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
        lo = min(c["l"], c["h"]) * ratio
        hi = max(c["l"], c["h"]) * ratio
        op = c["o"] * ratio
        cl = c["c"] * ratio
        lo_b = int(round(lo / 5.0)) * 5
        hi_b = int(round(hi / 5.0)) * 5
        rng = list(range(lo_b, hi_b + 5, 5))
        if not rng:
            continue
        b_lo, b_hi = min(op, cl), max(op, cl)
        weights = [2.5 if b_lo - 2.5 <= b <= b_hi + 2.5 else 1.0 for b in rng]
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

    prefix = f"[전일({sess_date}) 마감 · 09:30 ET 리셋] " if is_prior else ""
    return {
        "val": float(keys[lo_i]), "poc": float(poc), "vah": float(keys[hi_i]),
        "source": f"{source} x SPX/SPY 환산 · {prefix}{sess_date} 정규장 · 5pt 구간 POC",
    }


def compute_cvd(candles, tf_key, source, symbol="SPY", now_et=None):
    if not candles:
        return None
    tf_label = TF_LABEL.get(tf_key, tf_key)
    if now_et is None:
        now_et = datetime.now(ET)
    bars, is_prior, sess_date = get_rth_session(candles, now_et)
    if not bars:
        return None

    buy = sell = running = 0.0
    out = []
    for c in bars:
        v, h, l, cl = c["v"], c["h"], c["l"], c["c"]
        rng = h - l
        buy_ratio = (cl - l) / rng if rng > 0 else 0.5
        sell_ratio = (h - cl) / rng if rng > 0 else 0.5
        b_v = v * buy_ratio
        s_v = v * sell_ratio
        delta = b_v - s_v
        buy += b_v
        sell += s_v
        running += delta
        out.append({"t": c["t"], "vol": round(v / 1000.0, 2), "is_bull": delta >= 0, "cvd_line": round(running / 1000.0, 2)})

    total = buy + sell
    if total <= 0:
        return None
    buy_pct = int(round(buy / total * 100))
    sell_pct = 100 - buy_pct
    status, tone = ("Buying Pressure", "bull") if buy_pct >= 53 else (("Selling Pressure", "bear") if buy_pct <= 47 else ("Balanced", "flat"))
    text = f"CVD Flow: Buy {buy_pct}% / Sell {sell_pct}% in session."

    end_ts = bars[-1]["t"]
    aggregate_range = f"{sess_date} {'전일' if is_prior else ''}정규장 (09:30 ~ {et_time_sec(end_ts)}) · {len(bars)}개 {tf_label} 봉"
    prefix = f"[전일({sess_date}) 마감 · 09:30 ET 리셋] " if is_prior else ""

    return {
        "source": f"{source} {'· [전일 마감]' if is_prior else ''}",
        "data_time": et_label_sec(end_ts), "last_bar_time": et_time_sec(end_ts),
        "is_prior": is_prior, "session_date": sess_date,
        "status": f"{status}{' (전일)' if is_prior else ''}", "tone": tone,
        "aggregate_range": aggregate_range,
        "data_desc": f"{symbol} {prefix}정규장 · {source} · 체결 압력 CVD",
        "buy_pct": buy_pct, "sell_pct": sell_pct, "buy_vol": fmt_vol(buy), "sell_vol": fmt_vol(sell),
        "recent_vol": fmt_vol(bars[-1]["v"]), "total_vol": fmt_vol(total),
        "bars": out, "summary_text": text,
    }


# ─────────────────────────────────────────────────────────────
# GEX (0DTE 실시간 Volume+OI 결합)
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
                    K = num(o.get("strikePrice")) or num(skey)
                    if K is None:
                        continue
                    iv = num(o.get("volatility"))
                    contracts.append({
                        "K": K, "side": side, "oi": num(o.get("openInterest")) or 0.0,
                        "vol": num(o.get("totalVolume")) or num(o.get("volume")) or 0.0,
                        "iv": _valid_iv(iv / 100.0) if iv is not None else None,
                        "gamma": _valid_gamma(o.get("gamma")),
                        "bid": num(o.get("bid")), "ask": num(o.get("ask")), "last": num(o.get("last")),
                    })
    return contracts


def fetch_schwab_chain(token, today_date):
    if not token:
        return None, {"reason": "토큰 없음"}

    def ask(sym, from_date, to_date, strike_count):
        return schwab_get(token, "/chains", {"symbol": sym, "contractType": "ALL", "strikeCount": strike_count, "includeUnderlyingQuote": "false", "fromDate": from_date.isoformat(), "toDate": to_date.isoformat()}, timeout=6)

    today_str = today_date.isoformat()
    data = ask("$SPX", today_date, today_date, 160)
    exps = _chain_exps(data)
    used_sym = "$SPX"

    if today_str not in exps:
        data_spxw = ask("$SPXW", today_date, today_date, 160)
        exps_spxw = _chain_exps(data_spxw)
        if today_str in exps_spxw:
            data, exps, used_sym = data_spxw, exps_spxw, "$SPXW"

    if not exps:
        return None, {"reason": "만기 없음"}
    exp = today_str if today_str in exps else exps[0]
    contracts = parse_schwab_chain(data, exp)
    return (contracts, exp) if contracts else None, {"used_symbol": used_sym, "is_0dte": exp == today_str}


def fetch_yahoo_chain(start_date):
    try:
        import yfinance as yf
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
                    "K": K, "side": side, "oi": num(row.get("openInterest")) or 0.0,
                    "vol": num(row.get("volume")) or 0.0, "iv": _valid_iv(row.get("impliedVolatility")),
                    "gamma": None, "bid": num(row.get("bid")), "ask": num(row.get("ask")), "last": num(row.get("lastPrice")),
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
        if m is not None:
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
    gamma_schwab = gamma_calc = 0
    for c in use:
        raw_g = c["gamma"]
        g = raw_g or (bs_gamma(S, c["K"], T, c["iv"]) if c["iv"] else None)
        if g:
            gamma_schwab += 1 if raw_g else 0
            gamma_calc += 0 if raw_g else 1

        e = per.setdefault(c["K"], {"call_gex": 0.0, "put_gex": 0.0, "call_oi": 0.0, "put_oi": 0.0, "call_vol": 0.0, "put_vol": 0.0})
        eff_qty = max(c["oi"], c.get("vol", 0.0))

        if c["side"] == "C":
            e["call_oi"] += c["oi"]
            e["call_vol"] += c.get("vol", 0.0)
        else:
            e["put_oi"] += c["oi"]
            e["put_vol"] += c.get("vol", 0.0)

        if not g or eff_qty <= 0:
            continue
        dg = g * eff_qty * 100.0 * S * S * 0.01
        if c["side"] == "C":
            e["call_gex"] += dg
        else:
            e["put_gex"] -= dg

    if not per:
        return None

    calls_gex = [k for k, e in per.items() if e["call_gex"] > 0]
    puts_gex = [k for k, e in per.items() if e["put_gex"] < 0]
    call_wall = max(calls_gex, key=lambda k: per[k]["call_gex"]) * scale if calls_gex else None
    put_wall = min(puts_gex, key=lambda k: per[k]["put_gex"]) * scale if puts_gex else None

    net_total = sum(e["call_gex"] + e["put_gex"] for e in per.values())
    flip, flip_note = gamma_flip_level(use, S, T)
    straddle = atm_straddle(contracts, S)
    em_pt = straddle * scale if straddle else None

    nearest = sorted(per.items(), key=lambda kv: abs(kv[0] - S))[:14]
    by_strike = []
    for K, e in sorted(nearest, key=lambda kv: kv[0]):
        net_m = (e["call_gex"] + e["put_gex"]) / 1e6
        by_strike.append({
            "strike": round(K * scale, 1), "call_oi": int(e["call_oi"]), "put_oi": int(e["put_oi"]),
            "call_vol": int(e["call_vol"]), "put_vol": int(e["put_vol"]), "net_gex_m": round(net_m, 1),
        })

    is_0dte_session = bool((now_et.hour < 16 and exp_date == now_et.date().isoformat() and secs > 0) or (now_et.hour >= 16 and exp_date >= now_et.date().isoformat()))
    gamma_source_note = f"감마 {gamma_schwab}개는 Schwab 제공값, {gamma_calc}개는 BS 실시간 계산값"

    return {
        "available": True, "source": source, "expiration": exp_date, "is_0dte": is_0dte_session,
        "call_wall": round(call_wall, 1) if call_wall is not None else None,
        "put_wall": round(put_wall, 1) if put_wall is not None else None,
        "gamma_flip": round(flip * scale, 1) if flip is not None else None,
        "gamma_flip_note": flip_note, "em_pt": round(em_pt, 1) if em_pt else None,
        "expected_move": f"±{em_pt:.1f}pt ({em_pt / spot * 100:.2f}%)" if em_pt else None,
        "net_gex": fmt_dollars(net_total), "regime": "positive" if net_total >= 0 else "negative",
        "regime_text": "양(+) 감마 우세 - 딜러 헤지가 변동성을 억제" if net_total >= 0 else "음(−) 감마 우세 - 변동성 증폭 구간",
        "strike_count": len(per), "by_strike": by_strike, "gamma_source_note": gamma_source_note,
        "oi_skew": {
            "call_oi_at_or_above_spot": int(sum(e["call_oi"] for k, e in per.items() if k >= S)),
            "put_oi_at_or_above_spot": int(sum(e["put_oi"] for k, e in per.items() if k >= S)),
            "call_oi_below_spot": int(sum(e["call_oi"] for k, e in per.items() if k < S)),
            "put_oi_below_spot": int(sum(e["put_oi"] for k, e in per.items() if k < S)),
        },
    }


def get_gex(token, spx_p, ratio, now_et):
    if spx_p is None:
        return {"available": False, "source": "N/A", "reason": "SPX 현재가 없음"}
    start = now_et.date() if now_et.hour < 16 else now_et.date() + timedelta(days=1)

    def load():
        r, diag = fetch_schwab_chain(token, start)
        if r:
            res = analyze_gex(r[0], spx_p, 1.0, r[1], now_et, f"{SRC_SCHWAB} {diag.get('used_symbol','$SPX')} 체인 (실시간 Volume+OI 결합 GEX)", diag)
            if res:
                return res
        if ratio:
            ry = fetch_yahoo_chain(start)
            if ry:
                res = analyze_gex(ry[0], spx_p, ratio, ry[1], now_et, f"{SRC_YAHOO} SPY 체인 x 환산 · 근사치", diag)
                if res:
                    return res
        return {"available": False, "source": "N/A", "reason": "옵션체인 수집 실패"}

    return cached("gex", 15, load) or {"available": False, "source": "N/A", "reason": "GEX 조회 실패"}


# ─────────────────────────────────────────────────────────────
# 방향 분석 (0DTE 최적화: EMA 5/13/21 + CVD + VWAP 가중치)
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
    e5, e13, e21 = ema_series(closes, 5), ema_series(closes, 13), ema_series(closes, 21)
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

    score = max(-6.0, min(6.0, p_vs_e5 + e5_vs_e13 + e13_vs_e21 + e5_slope + bar_imp + rsi_score))
    label, tone = status_of(score)
    return {"score": round(score, 1), "status": label, "tone": tone}


def build_evidence(spx_p, vwap_val, c1h, cvd_data):
    ev = []
    if spx_p is not None and vwap_val is not None:
        diff = spx_p - vwap_val
        ev.append({"title": "VWAP 위치", "signal": "bull" if diff > 0 else ("bear" if diff < 0 else "flat"), "text": f"현재가가 당일 VWAP {'위' if diff > 0 else '아래'} ({diff:+.2f}pt)"})
    if cvd_data:
        ev.append({"title": "CVD 볼륨 압력", "signal": cvd_data["tone"], "text": f"{cvd_data['status']} (Buy {cvd_data['buy_pct']}% / Sell {cvd_data['sell_pct']}%)"})
    if len(c1h) >= 6:
        h3, h6 = max(c["h"] for c in c1h[-3:]), max(c["h"] for c in c1h[-6:-3])
        l3, l6 = min(c["l"] for c in c1h[-3:]), min(c["l"] for c in c1h[-6:-3])
        sig = "bull" if (h3 > h6 and l3 > l6) else ("bear" if (h3 < h6 and l3 < l6) else "flat")
        ev.append({"title": "상위(1H) 구조", "signal": sig, "text": f"1H 추세: {'고저점 상승' if sig=='bull' else ('고저점 하락' if sig=='bear' else '박스권')}"})
    return ev


def build_direction(tf_results, tf_sources, evidence, vwap_diff=None, cvd_data=None):
    avail = {k: v for k, v in tf_results.items() if v}
    if not avail:
        return {"available": False, "source": "N/A", "reason": "실시간 봉 수집 불가"}

    raw_score = sum(DIR_WEIGHTS[k] * avail[k]["score"] for k in avail) / sum(DIR_WEIGHTS[k] for k in avail)
    score = raw_score
    if vwap_diff is not None:
        score += 1.0 if vwap_diff > 1.0 else (-1.5 if vwap_diff < -1.0 else 0)
    if cvd_data:
        score += 1.0 if cvd_data.get("tone") == "bull" else (-1.5 if cvd_data.get("tone") == "bear" else 0)

    score = max(-6.0, min(6.0, score))
    label, tone = status_of(score)
    match_pct = int(round(sum(1 for v in avail.values() if v["tone"] == tone) / len(avail) * 100))

    summary = f"단기 모멘텀과 체결 압력이 {'상승' if tone=='bull' else ('하락' if tone=='bear' else '중립')} 쪽입니다. {match_pct}%의 시간봉이 일치합니다."
    kinds = {src_kind(tf_sources.get(k)) for k in avail}
    src = " + ".join({"schwab": "Charles Schwab", "yahoo": "Yahoo Finance"}[x] for x in ("schwab", "yahoo") if x in kinds) or "N/A"

    return {
        "available": True, "score": round(score, 1), "score_text": f"{score:+.1f}",
        "status": label, "tone": tone, "match_pct": match_pct, "summary": summary,
        "tfs": {k: ({**avail[k], "source": tf_sources.get(k)} if k in avail else None) for k in ("1h", "15m", "5m", "1m")},
        "evidence": evidence, "source": f"{src} (SPY) · 0DTE EMA(5/13/21)·VWAP·CVD 결합",
    }


# ─────────────────────────────────────────────────────────────
# 금리
# ─────────────────────────────────────────────────────────────
def yield_scale(raw_price):
    return 10.0 if (raw_price and raw_price > 25) else 1.0


# ─────────────────────────────────────────────────────────────
# API 엔드포인트
# ─────────────────────────────────────────────────────────────
@app.get("/api/test-alert")
def test_telegram_alert():
    now_et = datetime.now(ET)
    mock_shock = {
        "active": True, "type": "DROP", "level": "CRITICAL",
        "title": "🚨 [시스템 테스트] 텔레그램 연동 정상 작동 확인",
        "timestamp": now_et.strftime("%H:%M:%S ET"),
        "elapsed_text": f"{now_et.strftime('%H:%M ET')} 테스트 발송",
        "details": [
            "Vercel 환경변수(TELEGRAM_BOT_TOKEN / CHAT_ID) 연동 성공",
            "실제 시장 급변동(Flash Drop / Surge) 감지 시 자동 전송됩니다.",
            "동일 경보 10분 재발송 방지(쿨다운) 안전 로직 정상 가동 중"
        ]
    }
    result = send_telegram_shock_alert(mock_shock, spx_price=5750.0, force_test=True)
    return {"status": "ok", "time": now_et.strftime("%Y-%m-%d %H:%M:%S ET"), "result": result}


@app.get("/api/market-data")
def get_market_data(rsi_tf: str = "1H", cvd_tf: str = "10m"):
    now_et = datetime.now(ET)
    now_str = now_et.strftime("%m/%d %H:%M:%S ET")
    errors = []

    def guard(name, fn, *args):
        try:
            return fn(*args)
        except Exception as e:
            errors.append(f"{name}: {e}")
            return None

    token, schwab_msg = get_schwab_token()
    quotes = guard("quotes", get_all_quotes, token) or {}
    q_spx, q_spy = quotes.get("spx"), quotes.get("spy")
    spx_p = q_spx["price"] if q_spx else None
    ratio_q = (spx_p / q_spy["price"]) if (spx_p and q_spy and q_spy["price"]) else None

    r_key, c_key = normalize_tf(rsi_tf), normalize_tf(cvd_tf)
    with ThreadPoolExecutor(max_workers=8) as ex:
        f_spy_dir = {k: ex.submit(get_candles, token, "spy", k) for k in {"1h", "15m", "5m", "1m"}}
        f_spx_r = ex.submit(get_candles, token, "spx", r_key)
        f_spy_c = ex.submit(get_candles, token, "spy", c_key)
        f_gex = ex.submit(get_gex, token, spx_p, ratio_q, now_et)
        f_econ = ex.submit(get_today_econ_events, now_et)

    spy_dir_c = {k: guard(f"dir {k}", f.result) for k, f in f_spy_dir.items()}
    spx_r = guard("rsi", f_spx_r.result)
    spy_c = guard("cvd", f_spy_c.result)
    gex = guard("gex", f_gex.result) or {"available": False, "source": "N/A"}
    econ_events = guard("econ", f_econ.result) or {"items": [], "source": "N/A"}

    def ratio_for(spy_data):
        if ratio_q:
            return ratio_q
        if spx_p and spy_data and spy_data.get("candles"):
            return spx_p / spy_data["candles"][-1]["c"]
        return None

    # 1. 내부 VWAP (화면 차트는 제거되었으나 방향 판정에 100% 반영)
    spy_5m = spy_dir_c.get("5m")
    vwap_calc = guard("vwap", compute_vwap, spy_5m["candles"], ratio_for(spy_5m), now_et) if spy_5m else None

    # 2. Volume Profile
    vp = guard("vp", compute_volume_profile, spy_5m["candles"], ratio_for(spy_5m), spy_5m["source"], now_et) if (spy_5m and ratio_for(spy_5m)) else None

    # 3. CVD
    cvd = guard("cvd", compute_cvd, spy_c["candles"], c_key, spy_c["source"], "SPY", now_et) if spy_c else None

    # 4. RSI (헤더 실시간 배지용)
    rsi = None
    if spx_r:
        rs = rsi_series([c["c"] for c in spx_r["candles"]])
        if rs:
            cur = rs[-1]
            rsi = {
                "val": cur,
                "status": "과매수" if cur >= 70 else ("과매도" if cur <= 30 else ("상승" if cur >= 55 else ("하락" if cur <= 45 else "중립"))),
                "source": f"{spx_r['source']} · Wilder RSI(14)",
            }

    # 5. 방향 분석
    tf_results, tf_sources = {}, {}
    for k in ("1h", "15m", "5m", "1m"):
        d = spy_dir_c.get(k)
        tf_results[k] = guard(f"dir {k}", analyze_tf, d["candles"]) if d else None
        tf_sources[k] = d["source"] if d else None

    c1h = spy_dir_c["1h"]["candles"] if spy_dir_c.get("1h") else []
    vwap_diff = (spx_p - vwap_calc["val"]) if (spx_p and vwap_calc and vwap_calc.get("val")) else None
    evidence = build_evidence(spx_p, vwap_calc["val"] if vwap_calc else None, c1h, cvd)
    direction = guard("direction", build_direction, tf_results, tf_sources, evidence, vwap_diff, cvd) or {"available": False, "source": "N/A"}

    # 6. 실시간 변동성 쇼크 (VIX1D 우선 반영)
    spy_5m_bars = spy_dir_c.get("5m", {}).get("candles") if spy_dir_c.get("5m") else []
    vix_target = quotes.get("vix1d") or quotes.get("vix")
    shock_alert = guard("shock", detect_market_shock, spx_p, spy_5m_bars, ratio_for(spy_5m), gex, cvd, vix_target, now_et) or {"active": False}
    if shock_alert and shock_alert.get("active"):
        guard("telegram", send_telegram_shock_alert, shock_alert, spx_p)

    # 7. 국채 금리
    q10, q30, q3m = quotes.get("tnx"), quotes.get("tyx"), quotes.get("irx")

    def yield_info(q):
        if not q:
            return None, None
        s = yield_scale(q["price"])
        lvl = q["price"] / s
        bp = int(round((q["change"] / s) * 100)) if q.get("change") is not None else None
        return lvl, bp

    y10, y10_bp = yield_info(q10)
    y30, y30_bp = yield_info(q30)
    y3m, y3m_bp = yield_info(q3m)
    spread_bp = int(round((y10 - y3m) * 100)) if (y10 is not None and y3m is not None) else None

    yields = {
        "y3m": f"{y3m:.3f}%" if y3m else None, "y10": f"{y10:.3f}%" if y10 else None, "y30": f"{y30:.3f}%" if y30 else None,
        "y3m_change_text": f"{'+' if y3m_bp > 0 else ''}{y3m_bp} bp" if y3m_bp is not None else None,
        "y10_change_text": f"{'+' if y10_bp > 0 else ''}{y10_bp} bp" if y10_bp is not None else None,
        "y30_change_text": f"{'+' if y30_bp > 0 else ''}{y30_bp} bp" if y30_bp is not None else None,
        "spread": f"{'+' if spread_bp > 0 else ''}{spread_bp} bp" if spread_bp is not None else None,
        "sources": {"y3m": q3m["source"] if q3m else None, "y10": q10["source"] if q10 else None, "y30": q30["source"] if q30 else None},
    }

    def slim(q):
        return {"price": q["price"], "change": q["change"], "change_pct": q.get("change_pct"), "source": q["source"]} if q else None

    used = [q["source"] for q in quotes.values() if q]
    counts = {"schwab": sum(1 for s in used if src_kind(s) == "schwab"), "yahoo": sum(1 for s in used if src_kind(s) == "yahoo")}
    summary = f"Schwab {counts['schwab']} · Yahoo {counts['yahoo']}"

    return {
        "status": "success", "timestamp": now_str, "source_summary": summary, "schwab_status": schwab_msg,
        "shock_alert": shock_alert, "spx": q_spx, "es": quotes.get("es"),
        "vix1d": slim(quotes.get("vix1d")), "vix": slim(quotes.get("vix")),
        "mag7": quotes.get("mag7"), "econ_events": econ_events,
        "wti": quotes.get("wti"), "brent": quotes.get("brent"), "yields": yields,
        "volume_profile": vp, "gex": gex, "rsi": rsi, "cvd": cvd, "direction": direction,
    }


# ─────────────────────────────────────────────────────────────
# Schwab OAuth 콜백 (/api/callback)
# ─────────────────────────────────────────────────────────────
@app.get("/api/callback", response_class=HTMLResponse)
def schwab_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    if error or not code:
        return HTMLResponse("<h1>인증 실패</h1>", status_code=400)
    app_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_SECRET")
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI") or str(request.url).split("?")[0]
    res = requests.post(
        "https://api.schwabapi.com/v1/oauth/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
        auth=(app_key, app_secret),
        timeout=8,
    )
    if res.status_code != 200:
        return HTMLResponse("<h1>토큰 교환 실패</h1>", status_code=400)
    body = res.json()
    refresh_token = body.get("refresh_token", "")
    access_token = body.get("access_token", "")
    ttl = int(num(body.get("expires_in")) or 1800)
    if KV_AVAILABLE:
        now = time.time()
        kv_set(KV_KEY_REFRESH, refresh_token, ex_seconds=REFRESH_TOKEN_TTL)
        kv_set(KV_KEY_ACCESS, access_token, ex_seconds=ttl)
        kv_set(KV_KEY_ACCESS_EXP, str(now + ttl), ex_seconds=ttl)
    return HTMLResponse(f"<h1>✅ Schwab 인증 성공</h1><p>새 토큰이 등록되었습니다: {html_lib.escape(refresh_token[:20])}...</p>")
