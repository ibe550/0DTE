"""SPX 0DTE DEFENDER - market-data API (FastAPI on Vercel)"""
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
# 텔레그램 실시간 알림 시스템
# ─────────────────────────────────────────────────────────────
_LAST_TELEGRAM_SHOCK = {"ts": 0.0, "type": None}
TELEGRAM_COOLDOWN_SEC = 600


def send_telegram_shock_alert(shock_alert, spx_price, force_test=False):
    if not shock_alert or (not shock_alert.get("active") and not force_test):
        return {"status": "skipped", "reason": "알림 비활성"}
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_ids_raw = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_ids_raw:
        return {"status": "error", "reason": "환경변수 누락"}

    now_ts = time.time()
    s_type = shock_alert.get("type")
    if not force_test:
        if now_ts - _LAST_TELEGRAM_SHOCK["ts"] < TELEGRAM_COOLDOWN_SEC and _LAST_TELEGRAM_SHOCK["type"] == s_type:
            return {"status": "skipped", "reason": "쿨다운 중"}

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
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": cid, "text": msg}, timeout=4)
            results.append({"chat_id": cid, "ok": r.status_code == 200})
        except Exception as e:
            results.append({"chat_id": cid, "error": str(e)})

    return {"status": "sent", "results": results}


# ─────────────────────────────────────────────────────────────
# 영속 저장소 & Schwab 인증
# ─────────────────────────────────────────────────────────────
def _kv_config():
    url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    return (url.rstrip("/"), token) if url and token else (None, None)


def kv_cmd(*args):
    url, token = _kv_config()
    if not url:
        return None
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=list(args), timeout=4)
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
_TOKEN = {"value": None, "exp": 0.0}
SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
KV_KEY_ACCESS = "schwab:access_token"
KV_KEY_ACCESS_EXP = "schwab:access_token_exp"
KV_KEY_REFRESH = "schwab:refresh_token"
REFRESH_TOKEN_TTL = 8 * 24 * 3600


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
        return None, "refresh_token 없음 - /api/callback 으로 인증 필요"

    try:
        res = requests.post(
            SCHWAB_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(app_key, app_secret) if app_secret else None,
            timeout=6,
        )
        if res.status_code == 200:
            body = res.json()
            access_token = body.get("access_token")
            new_refresh = body.get("refresh_token")
            ttl = int(num(body.get("expires_in")) or 1800)
            _TOKEN["value"] = access_token
            _TOKEN["exp"] = now + max(60, ttl - 120)
            if KV_AVAILABLE:
                kv_set(KV_KEY_ACCESS, access_token, ex_seconds=ttl)
                kv_set(KV_KEY_ACCESS_EXP, str(now + ttl), ex_seconds=ttl)
                if new_refresh:
                    kv_set(KV_KEY_REFRESH, new_refresh, ex_seconds=REFRESH_TOKEN_TTL)
            return access_token, "연결됨 (새로 갱신)"
    except Exception:
        pass
    return None, "Schwab 토큰 갱신 실패"


def schwab_get(token, path, params=None, timeout=4):
    if not token:
        return None
    try:
        r = requests.get(f"{SCHWAB_BASE_URL}{path}", headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────
# 실시간 시세 (VIX 1D + VIX)
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
    if isinstance(data, dict):
        for sym in symbols:
            q = data.get(sym, {}).get("quote") if isinstance(data.get(sym), dict) else None
            if isinstance(q, dict):
                p = q.get("lastPrice") or q.get("mark")
                item = make_quote(p, q.get("closePrice"), q.get("netChange"), f"{SRC_SCHWAB} ({sym})")
                if item:
                    out[sym] = item
    return out


def fetch_yahoo_chart(symbol, interval="5m", range_str="1d"):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_str}"
        res = requests.get(url, headers=HEADERS, timeout=4)
        if res.status_code == 200:
            return (res.json().get("chart", {}).get("result") or [{}])[0] or {}
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
        need = []
        for key, (ssym, _) in QUOTES.items():
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
# 경제 캘린더 (실시간 발표치 분석 + 지수 영향 판정)
# ─────────────────────────────────────────────────────────────
ECON_TITLE_KR = {
    "Average Hourly Earnings m/m": "시간당 평균 임금 (MoM)",
    "Average Hourly Earnings y/y": "시간당 평균 임금 (YoY)",
    "Non-Farm Employment Change": "비농업 고용지수 (NFP)",
    "Unemployment Rate": "실업률",
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
    "Unemployment Claims": "신규 실업수당 청구건수",
    "Advance GDP q/q": "GDP 성장률 (속보치)",
    "FOMC Statement": "FOMC 성명서 발표",
    "Federal Funds Rate": "연준 기준금리 결정",
    "FOMC Press Conference": "파월 의장 기자회견",
    "ISM Manufacturing PMI": "ISM 제조업 PMI",
    "ISM Services PMI": "ISM 서비스업 PMI",
    "Retail Sales m/m": "소매판매 (MoM)",
}

HIGH_IMPACT_KEYWORDS = [
    "pce", "cpi", "ppi", "employment", "non-farm", "unemployment", "claims",
    "gdp", "fomc", "fed ", "federal funds", "powell", "ism", "jolts",
    "retail sales", "hourly earnings"
]


def evaluate_econ_result(title_en, actual_str, forecast_str, previous_str):
    if not actual_str:
        return {
            "tag": None,
            "tone": "pending",
            "sentence": f"시장 예상치: {forecast_str}" + (f" (이전: {previous_str})" if previous_str else "")
        }

    act_num = _parse_val(actual_str)
    fc_num = _parse_val(forecast_str) if forecast_str else _parse_val(previous_str)
    cmp_label = "예상" if forecast_str else "이전"
    cmp_str = forecast_str or previous_str

    t_lower = title_en.lower()
    is_inflation = any(k in t_lower for k in ["cpi", "pce", "ppi", "hourly earnings", "price index"])
    is_unemployment = any(k in t_lower for k in ["unemployment rate", "unemployment claims", "jobless claims"])
    is_nfp = "non-farm" in t_lower or "employment change" in t_lower

    if act_num is not None and fc_num is not None:
        diff = act_num - fc_num
        if abs(diff) < 1e-5:
            return {
                "tag": "⚪ 부합 (중립)",
                "tone": "flat",
                "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 시장 예상치 부합 (중립)"
            }

        if is_inflation:
            if diff > 0:
                return {
                    "tag": "🔴 임금/물가 과열 (하락)",
                    "tone": "bear",
                    "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 인플레이션 압력 가중 (지수 악재)"
                }
            return {
                "tag": "🟢 임금/물가 안정 (상승)",
                "tone": "bull",
                "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 인플레이션 둔화 및 물가 안정 (지수 호재)"
            }

        elif is_unemployment:
            if diff > 0:
                return {
                    "tag": "⚠️ 실업 증가 (하락)",
                    "tone": "bear",
                    "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 실업률/실업수당 증가 (경기 둔화 악재)"
                }
            return {
                "tag": "🟢 실업 감소 (상승)",
                "tone": "bull",
                "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 실업 감소 및 고용 안정 (지수 호재)"
            }

        elif is_nfp:
            if diff > 0:
                return {
                    "tag": "🟢 고용 서프라이즈 (상승)",
                    "tone": "bull",
                    "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 일자리 대폭 증가 (경기 연착륙 호재)"
                }
            return {
                "tag": "🔴 고용 쇼크 (하락)",
                "tone": "bear",
                "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 일자리 부진/고용 급랭 우려 (지수 악재)"
            }

        else:
            if diff > 0:
                return {
                    "tag": "🟢 경기 호조 (상승)",
                    "tone": "bull",
                    "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 경기 지표 강세 (지수 호재)"
                }
            return {
                "tag": "🔴 경기 위축 (하락)",
                "tone": "bear",
                "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 경기 지표 부진 (지수 악재)"
            }

    return {
        "tag": "발표 완료",
        "tone": "flat",
        "sentence": f"실제 {actual_str} ({cmp_label}: {cmp_str})"
    }


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
                "title": kr_name,
                "title_en": title,
                "dt": dt_obj,
                "ts": dt_obj.timestamp(),
                "time": dt_obj.strftime("%H:%M ET"),
                "impact": impact,
                "forecast": (it.get("forecast") or "").strip(),
                "previous": (it.get("previous") or "").strip(),
                "actual": (it.get("actual") or "").strip()
            })
        return parsed
    except Exception:
        return None


def get_today_econ_events(now_et):
    # 장중 실시간 발표치를 바로 캐치할 수 있도록 캐시 TTL을 20초로 단축
    events = cached("econ_events_data", 20, fetch_global_econ_calendar)
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
        has_actual = bool(it["actual"])
        prefix = f"[{it['dt'].strftime('%m/%d')}] " if is_tomorrow else ""
        eval_res = evaluate_econ_result(it["title_en"], it["actual"], it["forecast"], it["previous"])

        out_items.append({
            "title": f"{prefix}{it['title']}",
            "title_en": it["title_en"],
            "time": it["time"],
            "ts": it["ts"],
            "passed": passed,
            "has_actual": has_actual,
            "impact": it.get("impact", "High"),
            "actual": it["actual"],
            "forecast": it["forecast"],
            "previous": it["previous"],
            "eval_tag": eval_res["tag"],
            "eval_tone": eval_res["tone"],
            "eval_sentence": eval_res["sentence"],
        })

    return {"items": out_items, "source": "공식 경제 캘린더 (실시간 판정 · ET 전용)", "error": None}


# ─────────────────────────────────────────────────────────────
# 캔들 데이터 / CVD / Volume Profile
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
    data = schwab_get(token, "/pricehistory", {"symbol": symbol, "periodType": "day", "period": days, "frequencyType": "minute", "frequency": freq, "endDate": now_ms, "needExtendedHoursData": "true"}, timeout=5)
    out = []
    if isinstance(data, dict):
        for cd in data.get("candles") or []:
            if isinstance(cd, dict):
                o, h, l, c, t = num(cd.get("open")), num(cd.get("high")), num(cd.get("low")), num(cd.get("close")), num(cd.get("datetime"))
                if None not in (o, h, l, c, t):
                    out.append({"t": int(t / 1000), "o": o, "h": h, "l": l, "c": c, "v": num(cd.get("volume")) or 0.0})
    return out


def aggregate_candles(candles, minutes):
    groups = OrderedDict()
    for cd in candles:
        dt = datetime.fromtimestamp(cd["t"], ET)
        key = (dt.date(), (dt.hour * 60 + dt.minute - 570) // minutes)
        if key not in groups:
            groups[key] = dict(cd)
        else:
            groups[key]["h"] = max(groups[key]["h"], cd["h"])
            groups[key]["l"] = min(groups[key]["l"], cd["l"])
            groups[key]["c"] = cd["c"]
            groups[key]["v"] += cd["v"]
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
    is_after = is_weekday and (now_et.hour >= 16)

    sessions = OrderedDict()
    for c in candles:
        dt = datetime.fromtimestamp(c["t"], ET)
        d = dt.date()
        d_open = int(ET.localize(datetime(d.year, d.month, d.day, 9, 30, 0)).timestamp())
        d_close = int(ET.localize(datetime(d.year, d.month, d.day, 16, 0, 0)).timestamp())
        if d_open <= c["t"] <= d_close:
            sessions.setdefault(d, []).append(c)

    all_dates = sorted(sessions.keys())
    if is_rth:
        return sessions.get(today, []), False, today.strftime("%m/%d")
    if is_after and today in sessions:
        return sessions[today], False, today.strftime("%m/%d")
    priors = [d for d in all_dates if d < today]
    if priors:
        return sessions[priors[-1]], True, priors[-1].strftime("%m/%d")
    if all_dates:
        return sessions[all_dates[-1]], (all_dates[-1] != today), all_dates[-1].strftime("%m/%d")
    return [], False, today.strftime("%m/%d")


def compute_vwap(spy_candles, ratio, now_et=None):
    sess, _, _ = get_rth_session(spy_candles, now_et)
    if not sess or not ratio:
        return None
    cum_v = cum_tp = 0.0
    val = None
    for c in sess:
        if c["v"] <= 0:
            continue
        tp = (c["h"] + c["l"] + c["c"]) / 3.0 * ratio
        cum_v += c["v"]
        cum_tp += tp * c["v"]
        val = cum_tp / cum_v
    return {"val": round(val, 2)} if val else None


def compute_volume_profile(spy_candles, ratio, source, now_et=None):
    sess, is_prior, sess_date = get_rth_session(spy_candles, now_et)
    if not sess or not ratio:
        return None
    bins, total = {}, 0.0
    for c in sess:
        if c["v"] <= 0:
            continue
        lo, hi = min(c["l"], c["h"]) * ratio, max(c["l"], c["h"]) * ratio
        b_lo, b_hi = min(c["o"], c["c"]) * ratio, max(c["o"], c["c"]) * ratio
        lo_b, hi_b = int(round(lo / 5.0)) * 5, int(round(hi / 5.0)) * 5
        rng = list(range(lo_b, hi_b + 5, 5))
        if not rng:
            continue
        weights = [2.5 if b_lo - 2.5 <= b <= b_hi + 2.5 else 1.0 for b in rng]
        w_sum = sum(weights)
        for b, w in zip(rng, weights):
            each = c["v"] * (w / w_sum)
            bins[b] = bins.get(b, 0.0) + each
            total += each

    if not bins or total <= 0:
        return None
    keys = sorted(bins)
    poc = max(bins, key=bins.get)
    target = total * 0.70
    cur, lo_i, hi_i = bins[poc], keys.index(poc), keys.index(poc)
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
        b_v = v * buy_ratio
        s_v = v * (1.0 - buy_ratio)
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

    end_ts = bars[-1]["t"]
    aggregate_range = f"{sess_date} {'전일' if is_prior else ''}정규장 (09:30 ~ {datetime.fromtimestamp(end_ts, ET).strftime('%H:%M:%S ET')}) · {len(bars)}개 {tf_label} 봉"
    prefix = f"[전일({sess_date}) 마감 · 09:30 ET 리셋] " if is_prior else ""

    def fmt_v(v):
        return f"{v/1e6:.2f}M" if v >= 1e6 else (f"{v/1e3:.1f}K" if v >= 1e3 else f"{v:.0f}")

    return {
        "source": f"{source} {'· [전일 마감]' if is_prior else ''}",
        "data_time": datetime.fromtimestamp(end_ts, ET).strftime("%m/%d %H:%M:%S ET"),
        "last_bar_time": datetime.fromtimestamp(end_ts, ET).strftime("%H:%M:%S ET"),
        "is_prior": is_prior, "session_date": sess_date,
        "status": f"{status}{' (전일)' if is_prior else ''}", "tone": tone,
        "aggregate_range": aggregate_range,
        "data_desc": f"{symbol} {prefix}정규장 · {source} · 체결 압력 CVD",
        "buy_pct": buy_pct, "sell_pct": sell_pct, "buy_vol": fmt_v(buy), "sell_vol": fmt_v(sell),
        "recent_vol": fmt_v(bars[-1]["v"]), "total_vol": fmt_v(total),
        "bars": out, "summary_text": f"CVD Flow: Buy {buy_pct}% / Sell {sell_pct}% in session.",
    }


# ─────────────────────────────────────────────────────────────
# GEX & 방향 분석 & 변동성 쇼크
# ─────────────────────────────────────────────────────────────
def bs_gamma(S, K, T, sigma, r=0.0):
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
        g = pdf / (S * sigma * math.sqrt(T))
        return g if math.isfinite(g) else 0.0
    except Exception:
        return 0.0


def ema_series(values, period):
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


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
    calc = lambda g, l: 50.0 if l == 0 and g == 0 else (100.0 if l == 0 else 100.0 - (100.0 / (1.0 + g / l)))
    out = [round(calc(avg_g, avg_l), 1)]
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        out.append(round(calc(avg_g, avg_l), 1))
    return out


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
                        "iv": (iv / 100.0) if iv and 0.01 <= (iv / 100.0) <= 5.0 else None,
                        "gamma": num(o.get("gamma")), "bid": num(o.get("bid")), "ask": num(o.get("ask")), "last": num(o.get("last")),
                    })
    return contracts


def fetch_schwab_chain(token, today_date):
    if not token:
        return None, {"reason": "토큰 없음"}
    t_str = today_date.isoformat()
    data = schwab_get(token, "/chains", {"symbol": "$SPX", "contractType": "ALL", "strikeCount": 160, "includeUnderlyingQuote": "false", "fromDate": t_str, "toDate": t_str}, timeout=6)
    used_sym = "$SPX"
    exps = set()
    if isinstance(data, dict):
        for mk in ("callExpDateMap", "putExpDateMap"):
            for k in (data.get(mk) or {}).keys():
                exps.add(k.split(":")[0])
    if t_str not in exps:
        data_spxw = schwab_get(token, "/chains", {"symbol": "$SPXW", "contractType": "ALL", "strikeCount": 160, "includeUnderlyingQuote": "false", "fromDate": t_str, "toDate": t_str}, timeout=6)
        if isinstance(data_spxw, dict):
            data, used_sym = data_spxw, "$SPXW"
            exps = {k.split(":")[0] for mk in ("callExpDateMap", "putExpDateMap") for k in (data.get(mk) or {}).keys()}
    if not exps:
        return None, {"reason": "만기 없음"}
    exp = t_str if t_str in exps else sorted(exps)[0]
    contracts = parse_schwab_chain(data, exp)
    return (contracts, exp) if contracts else None, {"used_symbol": used_sym, "is_0dte": exp == t_str}


def analyze_gex(contracts, spot, scale, exp_date, now_et, source, diag=None):
    S = spot / scale
    y, m, d = (int(x) for x in exp_date.split("-"))
    exp_dt = ET.localize(datetime(y, m, d, 16, 0))
    secs = max((exp_dt - now_et).total_seconds(), 1800.0)
    T = secs / SECONDS_PER_YEAR

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

        if g and eff_qty > 0:
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

    # ATM Straddle
    by_k = {}
    for c in contracts:
        m_val = ((c["bid"] + c["ask"]) / 2.0) if (c.get("bid") and c.get("ask")) else c.get("last")
        if m_val:
            by_k.setdefault(c["K"], {})[c["side"]] = m_val
    both = {k: v for k, v in by_k.items() if "C" in v and "P" in v}
    straddle = (both[min(both, key=lambda x: abs(x - S))]["C"] + both[min(both, key=lambda x: abs(x - S))]["P"]) if both else None
    em_pt = straddle * scale if straddle else None

    by_strike = []
    for K, e in sorted(sorted(per.items(), key=lambda kv: abs(kv[0] - S))[:14], key=lambda kv: kv[0]):
        by_strike.append({
            "strike": round(K * scale, 1), "call_oi": int(e["call_oi"]), "put_oi": int(e["put_oi"]),
            "call_vol": int(e["call_vol"]), "put_vol": int(e["put_vol"]),
            "net_gex_m": round((e["call_gex"] + e["put_gex"]) / 1e6, 1),
        })

    is_0dte_session = bool((now_et.hour < 16 and exp_date == now_et.date().isoformat()) or (now_et.hour >= 16 and exp_date >= now_et.date().isoformat()))

    return {
        "available": True, "source": source, "expiration": exp_date, "is_0dte": is_0dte_session,
        "call_wall": round(call_wall, 1) if call_wall else None, "put_wall": round(put_wall, 1) if put_wall else None,
        "gamma_flip": round(spot, 1), "gamma_flip_note": None,
        "em_pt": round(em_pt, 1) if em_pt else None, "expected_move": f"±{em_pt:.1f}pt ({em_pt / spot * 100:.2f}%)" if em_pt else None,
        "net_gex": fmt_dollars(net_total), "regime": "positive" if net_total >= 0 else "negative",
        "regime_text": "양(+) 감마 우세 - 딜러 헤지가 변동성 억제" if net_total >= 0 else "음(−) 감마 우세 - 변동성 증폭 구간",
        "strike_count": len(per), "by_strike": by_strike,
        "gamma_source_note": f"감마 {gamma_schwab}개 Schwab 제공값, {gamma_calc}개 BS 실시간 계산값",
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
            return analyze_gex(r[0], spx_p, 1.0, r[1], now_et, f"{SRC_SCHWAB} {diag.get('used_symbol','$SPX')} 체인 (실시간 Volume+OI 결합 GEX)", diag)
        return {"available": False, "source": "N/A", "reason": "옵션 체인 수집 불가"}

    return cached("gex", 15, load) or {"available": False, "source": "N/A", "reason": "GEX 조회 실패"}


def detect_market_shock(spx_p, spy_5m_candles, ratio, gex, cvd, vix_active, now_et):
    if not spx_p:
        return {"active": False}
    today = now_et.date()
    is_rth = (now_et.weekday() < 5) and ((now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)) and now_et.hour < 16)
    if not is_rth:
        return {"active": False}

    today_open_ts = int(ET.localize(datetime(today.year, today.month, today.day, 9, 30, 0)).timestamp())
    today_bars = [c for c in (spy_5m_candles or []) if c["t"] >= today_open_ts]
    recent_bars = today_bars[-6:] if len(today_bars) >= 2 else []

    reasons, shock_type, level = [], "NORMAL", "NORMAL"
    elapsed_text = ""

    if recent_bars and ratio:
        high_bar = max(recent_bars, key=lambda b: b["h"])
        low_bar = min(recent_bars, key=lambda b: b["l"])
        curr_c = recent_bars[-1]["c"] * ratio
        drop = curr_c - (high_bar["h"] * ratio)
        rally = curr_c - (low_bar["l"] * ratio)

        if drop <= -14.0:
            elapsed_min = int(max((now_et.timestamp() - high_bar["t"]) // 60, 1))
            if elapsed_min <= 30:
                shock_type = "DROP"
                level = "CRITICAL" if drop <= -24.0 else "WARNING"
                s_label = datetime.fromtimestamp(high_bar["t"], ET).strftime("%H:%M ET")
                elapsed_text = f"{s_label} 시작 ({elapsed_min}분 경과)"
                reasons.append(f"{s_label}부터 {drop:.1f}pt 단기 급락 발생")

        elif rally >= 14.0:
            elapsed_min = int(max((now_et.timestamp() - low_bar["t"]) // 60, 1))
            if elapsed_min <= 30:
                shock_type = "SURGE"
                level = "CRITICAL" if rally >= 24.0 else "WARNING"
                s_label = datetime.fromtimestamp(low_bar["t"], ET).strftime("%H:%M ET")
                elapsed_text = f"{s_label} 시작 ({elapsed_min}분 경과)"
                reasons.append(f"{s_label}부터 +{rally:.1f}pt 단기 급등 발생")

    if gex and gex.get("available") and gex.get("is_0dte"):
        pw, cw = gex.get("put_wall"), gex.get("call_wall")
        if pw and spx_p < pw:
            reasons.append(f"Put Wall 지지선({pw:.1f}) 하향 붕괴 이탈 ({spx_p - pw:.1f}pt)")
            shock_type, level = "DROP", "CRITICAL"
        if cw and spx_p > cw:
            reasons.append(f"Call Wall 저항선({cw:.1f}) 상향 돌파 (+{spx_p - cw:.1f}pt)")
            shock_type, level = "SURGE", "CRITICAL"

    if cvd and not cvd.get("is_prior"):
        if cvd.get("sell_pct", 0) >= 65 and shock_type == "DROP":
            reasons.append(f"기관 매도 덤핑 폭발 (Sell {cvd['sell_pct']}%)")
        elif cvd.get("buy_pct", 0) >= 65 and shock_type == "SURGE":
            reasons.append(f"기관 매수 스퀴즈 유입 (Buy {cvd['buy_pct']}%)")

    if vix_active and shock_type == "DROP":
        vix_pct = vix_active.get("change_pct")
        if vix_pct and vix_pct >= 6.0:
            reasons.append(f"0DTE 변동성(VIX1D) 스파이크 폭등 (+{vix_pct:.1f}%)")

    is_active = len(reasons) > 0 and (shock_type in ("DROP", "SURGE"))
    title = "🚨 [변동성 쇼크 · 급락 경보]" if shock_type == "DROP" and level == "CRITICAL" else ("⚠️ [변동성 쇼크 · 하방 주의보]" if shock_type == "DROP" else ("🚀 [변동성 쇼크 · 급등 경보]" if level == "CRITICAL" else "⚡ [변동성 쇼크 · 상방 모멘텀]"))

    return {
        "active": is_active, "type": shock_type, "level": level, "title": title,
        "elapsed_text": elapsed_text, "details": reasons, "timestamp": now_et.strftime("%H:%M:%S ET")
    }


def analyze_tf(candles):
    closes = [c["c"] for c in candles]
    if len(closes) < 15:
        return None
    e5, e13, e21 = ema_series(closes, 5), ema_series(closes, 13), ema_series(closes, 21)
    p_vs_e5 = 1.0 if closes[-1] > e5[-1] else -1.0
    e5_vs_e13 = 1.0 if e5[-1] > e13[-1] else -1.0
    e13_vs_e21 = 1.0 if e13[-1] > e21[-1] else -1.0
    e5_slope = 1.0 if (len(e5) >= 2 and e5[-1] > e5[-2]) else -1.0

    rs = rsi_series(closes, period=9)
    rsi_val = rs[-1] if rs else 50.0
    rsi_score = 1.0 if rsi_val >= 55 else (-1.0 if rsi_val <= 45 else 0.0)

    score = max(-6.0, min(6.0, p_vs_e5 + e5_vs_e13 + e13_vs_e21 + e5_slope + rsi_score))
    label, tone = ("상승 우세", "bull") if score >= 3.0 else (("상승 편향", "bull") if score >= 1.2 else (("중립", "flat") if score > -1.2 else (("하락 편향", "bear") if score > -3.0 else ("하락 우세", "bear"))))
    return {"score": round(score, 1), "status": label, "tone": tone}


def build_direction(tf_results, tf_sources, spx_p, vwap_calc, c1h, cvd_data):
    avail = {k: v for k, v in tf_results.items() if v}
    if not avail:
        return {"available": False, "source": "N/A", "reason": "실시간 봉 수집 불가"}

    weights = {"5m": 0.35, "1m": 0.25, "15m": 0.25, "1h": 0.15}
    score = sum(weights[k] * avail[k]["score"] for k in avail) / sum(weights[k] for k in avail)

    vwap_diff = (spx_p - vwap_calc["val"]) if (spx_p and vwap_calc and vwap_calc.get("val")) else None
    if vwap_diff is not None:
        score += 1.0 if vwap_diff > 1.0 else (-1.5 if vwap_diff < -1.0 else 0)
    if cvd_data:
        score += 1.0 if cvd_data.get("tone") == "bull" else (-1.5 if cvd_data.get("tone") == "bear" else 0)

    score = max(-6.0, min(6.0, score))
    label, tone = ("상승 우세", "bull") if score >= 3.0 else (("상승 편향", "bull") if score >= 1.2 else (("중립", "flat") if score > -1.2 else (("하락 편향", "bear") if score > -3.0 else ("하락 우세", "bear"))))
    match_pct = int(round(sum(1 for v in avail.values() if v["tone"] == tone) / len(avail) * 100))

    evidence = []
    if vwap_diff is not None:
        evidence.append({"title": "VWAP 위치", "signal": "bull" if vwap_diff > 0 else ("bear" if vwap_diff < 0 else "flat"), "text": f"현재가가 당일 VWAP {'위' if vwap_diff > 0 else '아래'} ({vwap_diff:+.2f}pt)"})
    if cvd_data:
        evidence.append({"title": "CVD 볼륨 압력", "signal": cvd_data["tone"], "text": f"{cvd_data['status']} (Buy {cvd_data['buy_pct']}% / Sell {cvd_data['sell_pct']}%)"})

    return {
        "available": True, "score": round(score, 1), "score_text": f"{score:+.1f}",
        "status": label, "tone": tone, "match_pct": match_pct,
        "summary": f"단기 모멘텀과 체결 압력이 {'상승' if tone=='bull' else ('하락' if tone=='bear' else '중립')} 쪽입니다. {match_pct}% 일치.",
        "tfs": {k: ({**avail[k], "source": tf_sources.get(k)} if k in avail else None) for k in ("1h", "15m", "5m", "1m")},
        "evidence": evidence, "source": "Schwab+Yahoo (SPY) · 0DTE EMA(5/13/21)·VWAP·CVD 결합",
    }


# ─────────────────────────────────────────────────────────────
# API 엔드포인트
# ─────────────────────────────────────────────────────────────
@app.get("/api/test-alert")
def test_telegram_alert():
    now_et = datetime.now(ET)
    mock = {
        "active": True, "type": "DROP", "level": "CRITICAL",
        "title": "🚨 [시스템 테스트] 텔레그램 연동 정상 작동 확인",
        "timestamp": now_et.strftime("%H:%M:%S ET"), "elapsed_text": f"{now_et.strftime('%H:%M ET')} 테스트 발송",
        "details": ["환경변수 연동 성공", "실시간 급변동 감지 시 이와 동일하게 자동 전송됩니다."]
    }
    return {"status": "ok", "result": send_telegram_shock_alert(mock, 5750.0, force_test=True)}


@app.get("/api/market-data")
def get_market_data(rsi_tf: str = "1H", cvd_tf: str = "10m"):
    now_et = datetime.now(ET)
    now_str = now_et.strftime("%m/%d %H:%M:%S ET")

    token, schwab_msg = get_schwab_token()
    quotes = get_all_quotes(token) or {}
    q_spx, q_spy = quotes.get("spx"), quotes.get("spy")
    spx_p = q_spx["price"] if q_spx else None
    ratio_q = (spx_p / q_spy["price"]) if (spx_p and q_spy and q_spy.get("price")) else None

    r_key, c_key = normalize_tf(rsi_tf), normalize_tf(cvd_tf)
    with ThreadPoolExecutor(max_workers=8) as ex:
        f_spy_dir = {k: ex.submit(get_candles, token, "spy", k) for k in {"1h", "15m", "5m", "1m"}}
        f_spx_r = ex.submit(get_candles, token, "spx", r_key)
        f_spy_c = ex.submit(get_candles, token, "spy", c_key)
        f_gex = ex.submit(get_gex, token, spx_p, ratio_q, now_et)
        f_econ = ex.submit(get_today_econ_events, now_et)

    spy_dir_c = {k: f.result() for k, f in f_spy_dir.items()}
    spx_r = f_spx_r.result()
    spy_c = f_spy_c.result()
    gex = f_gex.result() or {"available": False, "source": "N/A"}
    econ_events = f_econ.result() or {"items": [], "source": "N/A"}

    spy_5m = spy_dir_c.get("5m")
    ratio = ratio_q or ((spx_p / spy_5m["candles"][-1]["c"]) if (spx_p and spy_5m and spy_5m.get("candles")) else None)

    vwap_calc = compute_vwap(spy_5m["candles"], ratio, now_et) if spy_5m else None
    vp = compute_volume_profile(spy_5m["candles"], ratio, spy_5m["source"], now_et) if (spy_5m and ratio) else None
    cvd = compute_cvd(spy_c["candles"], c_key, spy_c["source"], "SPY", now_et) if spy_c else None

    rsi = None
    if spx_r and spx_r.get("candles"):
        rs = rsi_series([c["c"] for c in spx_r["candles"]])
        if rs:
            cur = rs[-1]
            rsi = {
                "val": cur,
                "status": "과매수" if cur >= 70 else ("과매도" if cur <= 30 else ("상승" if cur >= 55 else ("하락" if cur <= 45 else "중립"))),
                "source": f"{spx_r['source']} · Wilder RSI(14)",
            }

    tf_results, tf_sources = {}, {}
    for k in ("1h", "15m", "5m", "1m"):
        d = spy_dir_c.get(k)
        tf_results[k] = analyze_tf(d["candles"]) if (d and d.get("candles")) else None
        tf_sources[k] = d["source"] if d else None

    c1h = spy_dir_c["1h"]["candles"] if (spy_dir_c.get("1h") and spy_dir_c["1h"].get("candles")) else []
    direction = build_direction(tf_results, tf_sources, spx_p, vwap_calc, c1h, cvd)

    spy_5m_bars = spy_5m.get("candles") if spy_5m else []
    vix_target = quotes.get("vix1d") or quotes.get("vix")
    shock_alert = detect_market_shock(spx_p, spy_5m_bars, ratio, gex, cvd, vix_target, now_et)
    if shock_alert and shock_alert.get("active"):
        send_telegram_shock_alert(shock_alert, spx_p)

    def yield_info(q):
        if not q or q.get("price") is None:
            return None, None
        s = 10.0 if q["price"] > 25 else 1.0
        lvl = q["price"] / s
        bp = int(round((q["change"] / s) * 100)) if q.get("change") is not None else None
        return lvl, bp

    y10, y10_bp = yield_info(quotes.get("tnx"))
    y30, y30_bp = yield_info(quotes.get("tyx"))
    y3m, y3m_bp = yield_info(quotes.get("irx"))
    spread_bp = int(round((y10 - y3m) * 100)) if (y10 is not None and y3m is not None) else None

    yields = {
        "y3m": f"{y3m:.3f}%" if y3m else None, "y10": f"{y10:.3f}%" if y10 else None, "y30": f"{y30:.3f}%" if y30 else None,
        "y3m_change_text": f"{'+' if y3m_bp > 0 else ''}{y3m_bp} bp" if y3m_bp is not None else None,
        "y10_change_text": f"{'+' if y10_bp > 0 else ''}{y10_bp} bp" if y10_bp is not None else None,
        "y30_change_text": f"{'+' if y30_bp > 0 else ''}{y30_bp} bp" if y30_bp is not None else None,
        "spread": f"{'+' if spread_bp > 0 else ''}{spread_bp} bp" if spread_bp is not None else None,
        "sources": {"y3m": quotes.get("irx", {}).get("source"), "y10": quotes.get("tnx", {}).get("source"), "y30": quotes.get("tyx", {}).get("source")},
    }

    def slim(q):
        return {"price": q["price"], "change": q["change"], "change_pct": q.get("change_pct"), "source": q["source"]} if q else None

    used = [q["source"] for q in quotes.values() if q]
    counts = {"schwab": sum(1 for s in used if src_kind(s) == "schwab"), "yahoo": sum(1 for s in used if src_kind(s) == "yahoo")}

    return {
        "status": "success", "timestamp": now_str, "source_summary": f"Schwab {counts['schwab']} · Yahoo {counts['yahoo']}",
        "schwab_status": schwab_msg, "shock_alert": shock_alert, "spx": q_spx, "es": quotes.get("es"),
        "vix1d": slim(quotes.get("vix1d")), "vix": slim(quotes.get("vix")),
        "mag7": quotes.get("mag7"), "econ_events": econ_events,
        "wti": quotes.get("wti"), "brent": quotes.get("brent"), "yields": yields,
        "volume_profile": vp, "gex": gex, "rsi": rsi, "cvd": cvd, "direction": direction,
    }


@app.get("/api/callback", response_class=HTMLResponse)
def schwab_callback(request: Request, code: Optional[str] = None):
    if not code:
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
    return HTMLResponse(f"<h1>✅ Schwab 인증 성공</h1><p>새 토큰: {html_lib.escape(refresh_token[:20])}...</p>")
