"""SPX 0DTE DEFENDER - market-data API (FastAPI on Vercel)"""
import math
import os
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import html as html_lib
from typing import Optional
import xml.etree.ElementTree as ET_xml

import pytz
import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

app = FastAPI()
handler = app
application = app

# 기존 코드에 MAGS(MAG7 ETF)와 국채 금리 지표($IRX, $TNX, $TYX)를 추가합니다.
SCHWAB_QUOTES = OrderedDict([
    ("spx", "$SPX"), ("vix1d", "$VIX1D"), ("vix", "$VIX"), ("spy", "SPY"),
    ("es", "/ES"), ("wti", "/CL"), ("brent", "/BZ"), ("uso", "USO"),
    ("mag7", "MAGS"),       # MAG7 ETF (Schwab API용)
    ("yield-3m", "$IRX"),   # 3개월물 T-Bill
    ("yield-10y", "$TNX"),  # 10년물 국채 금리
    ("yield-30y", "$TYX")   # 30년물 국채 금리
])

def _find_quote(data, sym):
    """응답 키가 요청 심볼과 다를 수 있는 선물 대응 (/ES -> /ESZ26)"""
    info = data.get(sym)
    if isinstance(info, dict) and isinstance(info.get("quote"), dict):
        return info
    for v in data.values():
        if isinstance(v, dict) and (v.get("reference") or {}).get("product") == sym:
            return v
    return None

def fetch_schwab_quotes(token, symbols):
    if not token:
        return {}
    out = {}
    data = schwab_get(token, "/quotes", {"symbols": ",".join(symbols), "fields": "quote,reference"})
    if not isinstance(data, dict):
        return out
    bad = (data.get("errors") or {}).get("invalidSymbols")
    if bad:
        print(f"[schwab] invalid symbols: {bad}")   # 로깅으로 교체
    for sym in symbols:
        info = _find_quote(data, sym)
        q = info.get("quote") if info else None
        if not q:
            continue
        p = q.get("lastPrice") or q.get("mark")
        if not p:                      # 0 또는 None이면 건너뜀
            continue
        item = make_quote(p, q.get("closePrice"), q.get("netChange"), f"{SRC_SCHWAB} ({sym})")
        if item:
            out[sym] = item
    return out

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
    cleaned = (
        s.replace("%", "")
        .replace("K", "")
        .replace("k", "")
        .replace("M", "")
        .replace("m", "")
        .replace("B", "")
        .replace(",", "")
        .strip()
    )
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
    if hit:
        return hit[1]
    return None


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
    if s.startswith("Yahoo"):
        return "yahoo"
    return "other"


# ─────────────────────────────────────────────────────────────
# 영속 저장소 (Vercel KV / Redis)
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
_TOKEN = {"value": None, "exp": 0.0}
SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
KV_KEY_ACCESS = "schwab:access_token"
KV_KEY_ACCESS_EXP = "schwab:access_token_exp"
KV_KEY_REFRESH = "schwab:refresh_token"
REFRESH_TOKEN_TTL = 8 * 24 * 3600


# ─────────────────────────────────────────────────────────────
# 텔레그램 실시간 알림 시스템 (절대 쿨다운 10분)
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
        kv_last_ts = num(kv_get("alert:telegram:last_ts")) if KV_AVAILABLE else None
        last_ts = max(_LAST_TELEGRAM_SHOCK["ts"], kv_last_ts or 0.0)
        if now_ts - last_ts < TELEGRAM_COOLDOWN_SEC:
            return {"status": "skipped", "reason": "쿨다운 침묵 중"}

    _LAST_TELEGRAM_SHOCK["ts"] = now_ts
    _LAST_TELEGRAM_SHOCK["type"] = s_type
    if KV_AVAILABLE:
        kv_set("alert:telegram:last_ts", str(now_ts), ex_seconds=TELEGRAM_COOLDOWN_SEC)

    title = shock_alert.get("title", "⚡ [변동성 쇼크]")
    time_info = shock_alert.get("elapsed_text") or shock_alert.get("timestamp") or ""
    details_str = "\n".join(f"• {d}" for d in shock_alert.get("details", []))
    price_str = f"{spx_price:.2f}" if spx_price else "N/A"

    msg = (
        f"{title}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📍 SPX 현재가: {price_str}\n"
        f"⏱ 발생 시각: {time_info}\n\n"
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
# Schwab 토큰 인증 관리
# ─────────────────────────────────────────────────────────────
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
# 실시간 시세 (Schwab 지수 4종 + Yahoo 실시간 선물 3종 동시 병렬 조회)
# ─────────────────────────────────────────────────────────────
SCHWAB_QUOTES = OrderedDict([
    ("spx", "$SPX"),
    ("vix1d", "$VIX1D"),
    ("vix", "$VIX"),
    ("spy", "SPY"),
])

YAHOO_FUTURES = OrderedDict([
    ("es", "ES=F"),
    ("wti", "CL=F"),
    ("brent", "BZ=F"),
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
    if not token:
        return {}
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


def fetch_yahoo_realtime_future(ysym):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}?interval=1m&range=1d"
        res = requests.get(url, headers=HEADERS, timeout=3.5)
        if res.status_code == 200:
            meta = ((res.json().get("chart", {}).get("result") or [{}])[0] or {}).get("meta") or {}
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            return make_quote(meta.get("regularMarketPrice"), prev, None, f"Yahoo ({ysym})")
    except Exception:
        pass
    return None


def get_all_quotes(token):
    def load():
        result = {}
        with ThreadPoolExecutor(max_workers=4) as ex:
            f_schwab = ex.submit(fetch_schwab_quotes, token, list(SCHWAB_QUOTES.values()))
            f_y = {k: ex.submit(fetch_yahoo_realtime_future, ysym) for k, ysym in YAHOO_FUTURES.items()}

        schwab_data = f_schwab.result() or {}
        for key, ssym in SCHWAB_QUOTES.items():
            result[key] = schwab_data.get(ssym)
        for key, fut in f_y.items():
            try:
                result[key] = fut.result()
            except Exception:
                result[key] = None

        return result if any(result.values()) else None

    return cached("quotes", 4, load) or {}


# ─────────────────────────────────────────────────────────────
# FLASH 실시간 속보 엔진
# ─────────────────────────────────────────────────────────────
def fetch_flash_market_news():
    def _fetch():
        try:
            url = "https://news.google.com/rss/search?q=(S%26P500+OR+Stock+market+OR+Federal+Reserve+OR+Crude+Oil)+AND+(stocks+OR+economy+OR+rates)+when:2h&hl=en-US&gl=US&ceid=US:en"
            r = requests.get(url, headers=HEADERS, timeout=4.0)
            if r.status_code != 200:
                return []
            root = ET_xml.fromstring(r.text)
            news_items = []

            EXCLUDE_WORDS = [
                "shooting", "shooter", "gun", "police", "killed", "dead", "murder",
                "hurricane", "tornado", "floods", "storm", "crash", "arrested"
            ]

            for it in root.findall(".//item")[:4]:
                title = it.findtext("title", "")
                source = title.rsplit(" - ", 1)[1] if " - " in title else "Flash Wire"
                title = title.rsplit(" - ", 1)[0] if " - " in title else title
                t_lower = title.lower()

                if any(w in t_lower for w in EXCLUDE_WORDS):
                    continue

                bull_words = ["surge", "rally", "soar", "gain", "rate cut", "easing", "inflation cools"]
                bear_words = ["plunge", "tumble", "slump", "tariff", "rate hike", "recession", "sanction"]

                is_bull = any(w in t_lower for w in bull_words)
                is_bear = any(w in t_lower for w in bear_words)

                if is_bull and not is_bear:
                    tag = "🟢 지수 호재 (Bullish)"
                    tone = "bull"
                elif is_bear:
                    tag = "🔴 지수 악재 (Bearish)"
                    tone = "bear"
                else:
                    tag = "⚡ 실시간 속보 (Catalyst)"
                    tone = "pending"

                news_items.append({
                    "title": title.strip(),
                    "source": source.strip(),
                    "tag": tag,
                    "tone": tone,
                    "time": "속보",
                })
            return news_items
        except Exception:
            return []

    return cached("flash_market_news", 180, _fetch) or []


# ─────────────────────────────────────────────────────────────
# 연준 위원 발언 & 경제 캘린더
# ─────────────────────────────────────────────────────────────
FED_SPEAKERS = {
    "bowman": {"name": "보우만 이사", "stance": "매파(Hawkish)", "note": "추가 인상 희박/완화 발언 시 강력한 숏스퀴즈 호재"},
    "waller": {"name": "월러 이사", "stance": "매파/실세(Hawkish)", "note": "금리 경로 선행 지표 위원"},
    "powell": {"name": "파월 의장", "stance": "중립/의장(Centrist)", "note": "0DTE 양방향 변동성 극대화 주의"},
    "williams": {"name": "윌리엄스 총재", "stance": "중립/부의장(Centrist)", "note": "연준 핵심 지도부 컨센서스 대변"},
    "goolsbee": {"name": "굴스비 총재", "stance": "비둘기파(Dovish)", "note": "선제적 금리 인하 지지파"},
    "kashkari": {"name": "카시카리 총재", "stance": "매파(Hawkish)", "note": "고금리 장기화 선호 위원"},
    "bostic": {"name": "보스틱 총재", "stance": "중립/신중(Centrist)", "note": "완만한 완화 속도 선호"},
    "daly": {"name": "데일리 총재", "stance": "비둘기파(Dovish)", "note": "고용 냉각 경계 및 완화 지지"},
    "kugler": {"name": "쿠글러 이사", "stance": "비둘기파(Dovish)", "note": "노동시장 안정 및 완화 지지"},
}


def fetch_speaker_headline(speaker_key):
    def _get():
        try:
            url = f"https://news.google.com/rss/search?q=Fed+{speaker_key}+interest+rates&hl=en-US&gl=US&ceid=US:en"
            r = requests.get(url, headers=HEADERS, timeout=3.5)
            if r.status_code == 200:
                root = ET_xml.fromstring(r.text)
                for it in root.findall(".//item")[:3]:
                    t = it.findtext("title", "")
                    if speaker_key.lower() in t.lower() or "fed" in t.lower():
                        return t.rsplit(" - ", 1)[0] if " - " in t else t
        except Exception:
            pass
        return None

    return cached(f"fed_news:{speaker_key}", 180, _get)


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
    "gdp", "fomc", "fed ", "federal funds", "powell", "ism", "services pmi",
    "manufacturing pmi", "retail sales", "hourly earnings", "speaks", "speech"
]


def evaluate_econ_result(title_en, actual_str, forecast_str, previous_str, is_passed, elapsed_sec, market_reaction):
    t_lower = title_en.lower()
    is_speech = any(w in t_lower for w in ["speaks", "speech", "testifies", "press conference", "panel"])

    if is_speech:
        speaker_key = next((k for k in FED_SPEAKERS if k in t_lower), None)
        spk = FED_SPEAKERS.get(speaker_key, {"name": "연준 위원", "stance": "통화정책 위원", "note": "금리 발언 주의"})
        if not is_passed:
            return {"tag": f"🎙️ {spk['name']} 발언 예정", "tone": "flat", "sentence": f"{spk['stance']} · {spk['note']}"}

        headline = fetch_speaker_headline(speaker_key) if speaker_key else None
        if headline:
            h_lower = headline.lower()
            is_dovish = any(w in h_lower for w in ["unlikely", "cut", "cool", "ease", "progress", "slow", "no hike", "less likely"])
            is_hawkish = any(w in h_lower for w in ["hike", "raise", "sticky", "high for longer", "not ready", "too soon"])
            if is_dovish and not is_hawkish:
                return {"tag": "🟢 비둘기 발언 (호재)", "tone": "bull", "sentence": f"↳ 헤드라인: \"{headline}\" (추가 인상 희박/완화)"}
            elif is_hawkish:
                return {"tag": "🔴 매파 발언 (경계)", "tone": "bear", "sentence": f"↳ 헤드라인: \"{headline}\" (긴축 유지 경계)"}
            return {"tag": "🎙️ 발언 헤드라인", "tone": "flat", "sentence": f"↳ 헤드라인: \"{headline}\""}

        if market_reaction and market_reaction.get("detected"):
            mr = market_reaction
            tag = "🟢 시장 호재 반응" if mr["dir"] == "bull" else ("🔴 시장 악재 반응" if mr["dir"] == "bear" else "⚪ 시장 중립")
            return {"tag": f"{tag} ({mr['diff_str']})", "tone": mr["dir"], "sentence": f"{spk['name']} 발언 직후 SPX {mr['diff_str']} 변동 감지"}

        return {"tag": f"🎙️ {spk['name']} 발언 진행/종료", "tone": "flat", "sentence": f"{spk['stance']} · {spk['note']}"}

    act_num = _parse_val(actual_str)
    fc_num = _parse_val(forecast_str) if forecast_str else _parse_val(previous_str)
    cmp_label = "예상" if forecast_str else "이전"
    cmp_str = forecast_str or previous_str

    if act_num is not None and fc_num is not None:
        diff = act_num - fc_num
        is_inflation = any(k in t_lower for k in ["cpi", "pce", "ppi", "hourly earnings", "price index"])
        is_unemployment = any(k in t_lower for k in ["unemployment rate", "unemployment claims", "jobless claims"])
        is_nfp = "non-farm" in t_lower or "employment change" in t_lower
        is_pmi = "ism" in t_lower or "pmi" in t_lower

        if abs(diff) < 1e-5:
            tone, tag_label = "flat", "⚪ 부합 (중립)"
        elif is_pmi:
            tone, tag_label = ("bull", "🟢 서비스/제조업 확장 (상승)") if diff > 0 else ("bear", "🔴 서비스/제조업 위축 (하락)")
        elif is_inflation:
            tone, tag_label = ("bear", "🔴 물가 과열 (하락)") if diff > 0 else ("bull", "🟢 물가 안정 (상승)")
        elif is_unemployment:
            tone, tag_label = ("bear", "⚠️ 실업 증가 (하락)") if diff > 0 else ("bull", "🟢 실업 감소 (상승)")
        elif is_nfp:
            tone, tag_label = ("bull", "🟢 고용 서프라이즈 (상승)") if diff > 0 else ("bear", "🔴 고용 쇼크 (하락)")
        else:
            tone, tag_label = ("bull", "🟢 지표 호조 (상승)") if diff > 0 else ("bear", "🔴 지표 부진 (하락)")

        mr_suffix = f" · 시장 {market_reaction['diff_str']}" if (market_reaction and market_reaction.get("detected")) else ""
        return {"tag": tag_label, "tone": tone, "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str}{mr_suffix}"}

    if is_passed:
        if market_reaction and market_reaction.get("detected"):
            mr = market_reaction
            if mr["dir"] == "bull":
                return {"tag": f"🟢 시장 호재 반응 ({mr['diff_str']})", "tone": "bull", "sentence": f"수치 지연 중이나 발표 직후 SPX {mr['diff_str']} 급반등 (시장 호재 소화)"}
            elif mr["dir"] == "bear":
                return {"tag": f"🔴 시장 악재 반응 ({mr['diff_str']})", "tone": "bear", "sentence": f"수치 지연 중이나 발표 직후 SPX {mr['diff_str']} 급락 발생 (시장 악재 소화)"}
            else:
                return {"tag": "⚪ 시장 중립 소화", "tone": "flat", "sentence": f"발표 직후 지수 변동 미미 ({mr['diff_str']}) · 시장 중립/흡수 소화"}

        if elapsed_sec <= 600:
            return {"tag": "⏳ 속보 수신 중", "tone": "pending", "sentence": f"시장 예상치: {forecast_str or 'N/A'} (초기 체결 분석 중)"}

        return {"tag": "⚪ 발표 완료", "tone": "flat", "sentence": f"예상치 {forecast_str or 'N/A'} · 발표 완료 (시장 기저 반영)"}

    return {"tag": None, "tone": "pending", "sentence": f"시장 예상치: {forecast_str}" + (f" (이전: {previous_str})" if previous_str else "")}


def detect_event_market_reaction(event_ts, spy_5m_candles, ratio):
    if not spy_5m_candles or not ratio:
        return None
    matched_idx = None
    for idx, cd in enumerate(spy_5m_candles):
        if abs(cd["t"] - event_ts) < 240:
            matched_idx = idx
            break
    if matched_idx is None:
        for idx, cd in enumerate(spy_5m_candles):
            if cd["t"] >= event_ts:
                matched_idx = idx
                break
    if matched_idx is None or matched_idx >= len(spy_5m_candles):
        return None

    target_bar = spy_5m_candles[matched_idx]
    prev_bar = spy_5m_candles[matched_idx - 1] if matched_idx > 0 else target_bar
    diff_pt = (target_bar["c"] - prev_bar["c"]) * ratio
    diff_str = f"{diff_pt:+.1f}pt"

    if diff_pt >= 3.5:
        return {"detected": True, "dir": "bull", "diff_pt": diff_pt, "diff_str": diff_str}
    elif diff_pt <= -3.5:
        return {"detected": True, "dir": "bear", "diff_pt": diff_pt, "diff_str": diff_str}
    return {"detected": True, "dir": "flat", "diff_pt": diff_pt, "diff_str": diff_str}


def fetch_global_econ_calendar():
    now_sec = int(time.time())
    url = f"https://nfs.faireconomy.media/ff_calendar_thisweek.json?_={now_sec}"
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Accept": "application/json",
    }
    try:
        r = requests.get(url, headers=req_headers, timeout=5.0)
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
            if not ((impact in ("High", "Medium")) or any(k in t_lower for k in HIGH_IMPACT_KEYWORDS)):
                continue
            raw_date = it.get("date", "")
            if not raw_date:
                continue
            try:
                dt_obj = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).astimezone(ET)
            except Exception:
                continue

            kr_name = ECON_TITLE_KR.get(title)
            if not kr_name:
                for spk_k, spk_v in FED_SPEAKERS.items():
                    if spk_k in t_lower:
                        kr_name = f"연준 {spk_v['name']} 연설/발언"
                        break
            if not kr_name:
                kr_name = title

            parsed.append({
                "title": kr_name, "title_en": title, "dt": dt_obj, "ts": dt_obj.timestamp(),
                "time": dt_obj.strftime("%H:%M ET"), "impact": impact,
                "forecast": (it.get("forecast") or "").strip(), "previous": (it.get("previous") or "").strip(),
                "actual": (it.get("actual") or "").strip()
            })
        return parsed
    except Exception:
        return None

def get_today_econ_events(now_et, spy_5m_candles, ratio):
    events = cached("econ_events_data", 60, fetch_global_econ_calendar)
    flash_news = fetch_flash_market_news()
    now_ts = now_et.timestamp()
    if not events:
        return {"items": [], "flash_news": flash_news, "source": "N/A", "error": "경제 캘린더 조회 실패"}

    today = now_et.date()
    # 금요일 16:00 이후면 월요일(+3), 평일이면 익일(+1)
    days_ahead = 3 if today.weekday() == 4 else (2 if today.weekday() == 5 else 1)
    tomorrow = today + timedelta(days=days_ahead)

    is_tomorrow = False
    target_items = []

    # 16:00 ET 이후에는 오늘 밤 잔여 일정을 무시하고 익일(내일) 지표를 1순위로 강제 설정
    if now_et.hour >= 16:
        tomorrow_items = [e for e in events if e["dt"].date() == tomorrow]
        if tomorrow_items:
            target_items = tomorrow_items
            is_tomorrow = True
        else:
            future_events = [e for e in events if e["dt"].date() > today]
            if future_events:
                next_date = min(e["dt"].date() for e in future_events)
                target_items = [e for e in future_events if e["dt"].date() == next_date]
                is_tomorrow = True

    # 장중(16:00 ET 이전)이거나 미래 일정이 전혀 없을 때만 당일 이벤트 노출
    if not target_items:
        today_items = [e for e in events if e["dt"].date() == today]
        active_today_items = [e for e in today_items if (now_ts - e["ts"]) <= 3600]
        target_items = active_today_items if active_today_items else today_items
        is_tomorrow = False

    target_items.sort(key=lambda x: x["ts"])
    out_items = []
    for it in target_items:
        passed = (it["ts"] <= now_ts)
        elapsed_sec = int(now_ts - it["ts"]) if passed else 0
        if not is_tomorrow and passed and elapsed_sec > 3600:
            continue

        has_actual = bool(it["actual"])
        prefix = f"[{it['dt'].strftime('%m/%d')}] " if is_tomorrow else ""
        market_reaction = detect_event_market_reaction(it["ts"], spy_5m_candles, ratio) if passed else None
        eval_res = evaluate_econ_result(it["title_en"], it["actual"], it["forecast"], it["previous"], passed, elapsed_sec, market_reaction)

        out_items.append({
            "title": f"{prefix}{it['title']}", "title_en": it["title_en"], "time": it["time"],
            "ts": it["ts"], "passed": passed, "has_actual": has_actual, "impact": it.get("impact", "High"),
            "actual": it["actual"], "forecast": it["forecast"], "previous": it["previous"],
            "eval_tag": eval_res["tag"], "eval_tone": eval_res["tone"], "eval_sentence": eval_res["sentence"],
        })

    return {"items": out_items, "flash_news": flash_news, "source": "공식 캘린더 + Flash 속보 엔진", "error": None}

def fetch_polymarket_spx_data(spx_price):
    import json as _json
    import re
    from urllib.parse import quote

    now_et = datetime.now(ET)
    today = now_et.date()

    # 평일 16:00 ET 이후이거나 주말(토/일)이면 다음 거래일(월요일/익일) 일일 마켓 타겟팅
    if today.weekday() == 5:      # 토요일 -> 월요일(+2)
        target_date = today + timedelta(days=2)
    elif today.weekday() == 6:    # 일요일 -> 월요일(+1)
        target_date = today + timedelta(days=1)
    elif now_et.hour >= 16:       # 평일 장 마감 후 -> 다음 영업일
        days_ahead = 3 if today.weekday() == 4 else 1
        target_date = today + timedelta(days=days_ahead)
    else:
        target_date = today

    month_full = target_date.strftime("%B")        # 예: October
    month_short = target_date.strftime("%b")       # 예: Oct
    day_num = str(target_date.day)                 # 예: 19

    # SPY 완전 제외, 순수 S&P 500 / SPX 일일 마켓만 검색
    search_queries = [
        quote(f"S&P 500 {month_full} {day_num}"),
        quote(f"SPX {month_full} {day_num}"),
        quote("S&P 500 Up or Down"),
        quote("S&P 500 close"),
        quote("SPX close"),
    ]

    # 연말/월말/장기 마켓 및 SPY 원천 배제 키워드
    ban_keywords = [
        "spy", "etf", "end of year", "eoy", "end of month", "by end of",
        "in 2026", "in 2027", "by december", "in october", "in november",
        "all time high", "ath", "recession", "fed ", "interest rate", "president"
    ]

    candidates = []

    for q in search_queries:
        try:
            url = f"https://gamma-api.polymarket.com/public-search?q={q}&events_status=active&limit_per_type=20"
            r = requests.get(url, headers=HEADERS, timeout=4.0)
            if r.status_code != 200:
                continue

            data = r.json()
            events = data.get("events", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            if not events:
                continue

            for ev in events:
                if ev.get("closed"):
                    continue

                ev_title = (ev.get("title") or "").strip()
                t_low = ev_title.lower()

                # 오직 S&P 500 / SPX만 허용 (SPY 제외)
                if not any(k in t_low for k in ("s&p", "spx")):
                    continue
                if any(b in t_low for b in ban_keywords):
                    continue

                # 만기일(endDate) 체크: 오늘로부터 5일 이내에 마감되는 단기/일일 마켓만 통과
                end_str = str(ev.get("endDate") or "")[:10]
                if end_str:
                    try:
                        end_dt = datetime.strptime(end_str, "%Y-%m-%d").date()
                        days_diff = (end_dt - today).days
                        if days_diff < 0 or days_diff > 5:
                            continue
                    except Exception:
                        pass

                is_exact_date = (
                    f"{month_full.lower()} {day_num}" in t_low
                    or f"{month_short.lower()} {day_num}" in t_low
                    or f"{target_date.month}/{day_num}" in t_low
                )

                for m in (ev.get("markets") or []):
                    if m.get("closed") or m.get("active") is False:
                        continue

                    q_str = (m.get("question") or m.get("groupItemTitle") or "").strip()
                    q_low = q_str.lower()
                    if any(b in q_low for b in ban_keywords):
                        continue

                    raw_prices = m.get("outcomePrices")
                    if not raw_prices:
                        continue
                    prices = _json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
                    if not prices or len(prices) < 2:
                        continue

                    p0 = float(prices[0])
                    if not (0.02 <= p0 <= 0.98):
                        continue

                    # SPX 지수 범위(4,000 ~ 12,000)의 행사가만 추출 (3자리 SPY 가격 무시)
                    nums = [float(x.replace(",", "")) for x in re.findall(r"\d{1,2},\d{3}(?:\.\d+)?|\d{4}(?:\.\d+)?", q_str)]
                    strike_dist = 9999.0
                    extracted_strike = None
                    if nums:
                        for n in nums:
                            if 4000 <= n <= 12000 and int(n) not in (2025, 2026, 2027):
                                extracted_strike = int(round(n))
                                if spx_price:
                                    strike_dist = abs(n - spx_price)
                                break

                    atm_score = abs(p0 - 0.5)
                    sort_key = (0 if is_exact_date else 1, strike_dist, atm_score)
                    candidates.append((sort_key, ev_title, m, prices, extracted_strike))

            if any(c[0][0] == 0 for c in candidates):
                break
        except Exception:
            continue

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    _, best_ev_title, best_m, prices, extracted_strike = candidates[0]

    raw_outcomes = best_m.get("outcomes")
    outcomes = _json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else (raw_outcomes or ["Yes", "No"])

    yes_pct = int(round(float(prices[0]) * 100))
    no_pct = int(round(float(prices[1]) * 100))

    lbl_yes = str(outcomes[0]) if len(outcomes) > 0 else "Yes"
    lbl_no = str(outcomes[1]) if len(outcomes) > 1 else "No"
    if lbl_yes.lower() == "up":
        lbl_yes, lbl_no = "상승(Up)", "하락(Down)"
    elif lbl_yes.lower() in ("yes", "above"):
        lbl_yes, lbl_no = "상회(Yes)", "하회(No)"

    sub_item = (best_m.get("groupItemTitle") or "").strip()
    date_tag = target_date.strftime("%m/%d")
    if extracted_strike:
        display_title = f"[{date_tag}] SPX {extracted_strike}선 마감 확률"
    elif sub_item and sub_item not in best_ev_title:
        display_title = f"[{date_tag}] {best_ev_title} ({sub_item})"
    else:
        display_title = f"[{date_tag}] {(best_m.get('question') or best_ev_title).strip()}"

    vol = float(best_m.get("volume") or 0)
    vol_str = f" · 거래량 ${int(vol):,}" if vol > 0 else ""

    return {
        "available": True,
        "title": display_title,
        "yes_pct": yes_pct,
        "no_pct": no_pct,
        "summary": f"{lbl_yes} {yes_pct}% · {lbl_no} {no_pct}%",
        "source": f"Polymarket SPX{vol_str}"
    }


def get_polymarket_spx(spx_price):
    return cached("polymarket_spx_only", 60, lambda: fetch_polymarket_spx_data(spx_price)) or {
        "available": False,
        "title": "당일 SPX 일일 폴리마켓 개장 대기",
        "yes_pct": 0,
        "no_pct": 0,
        "summary": "차기 거래일 SPX 마켓 생성 대기 중",
        "source": "Polymarket SPX"
    }

# ─────────────────────────────────────────────────────────────
# 캔들 데이터 / CVD / Volume Profile (전 시간대 1분봉 실시간 정밀 합성)
# ─────────────────────────────────────────────────────────────
TF_SPEC = {
    "1m": (1, 2, None),
    "5m": (1, 2, 5),
    "10m": (1, 2, 10),
    "15m": (1, 2, 15),
    "30m": (1, 2, 30),
    "1h": (1, 5, 60),    # 1시간봉도 5일치 실시간 1분봉으로 합성 (장 시작 즉시 1H 봉 생성 + RSI 기간 확보)
}
TF_LABEL = {"1m": "1m", "5m": "5m", "10m": "10m", "15m": "15m", "30m": "30m", "1h": "1H"}
INSTR = {"spx": "$SPX", "spy": "SPY"}


def normalize_tf(tf):
    key = str(tf or "").strip().lower()
    return key if key in TF_SPEC else "10m"


def schwab_candles(token, symbol, freq, days):
    now_ms = int(time.time() * 1000)
    data = schwab_get(
        token,
        "/pricehistory",
        {
            "symbol": symbol,
            "periodType": "day",
            "period": days,
            "frequencyType": "minute",
            "frequency": freq,
            "endDate": now_ms,
            "needExtendedHoursData": "true",
        },
        timeout=5,
    )
    out = []
    if isinstance(data, dict):
        for cd in data.get("candles") or []:
            if isinstance(cd, dict):
                o, h, l, c, t = (
                    num(cd.get("open")),
                    num(cd.get("high")),
                    num(cd.get("low")),
                    num(cd.get("close")),
                    num(cd.get("datetime")),
                )
                if None not in (o, h, l, c, t):
                    out.append({"t": int(t / 1000), "o": o, "h": h, "l": l, "c": c, "v": num(cd.get("volume")) or 0.0})
    return out


def aggregate_candles(candles, minutes):
    groups = OrderedDict()
    for cd in candles:
        dt = datetime.fromtimestamp(cd["t"], ET)
        total_min = dt.hour * 60 + dt.minute

        # 정규장(09:30 = 570분) 기준으로 시간 슬롯 정렬 (09:30~10:29 -> 09:30 봉으로 생성되어 누락 원천 방지)
        if total_min >= 570:
            idx = (total_min - 570) // minutes
            slot_min = 570 + idx * minutes
        else:
            slot_min = (total_min // minutes) * minutes

        slot_h, slot_m = divmod(slot_min, 60)
        slot_ts = int(ET.localize(datetime(dt.year, dt.month, dt.day, slot_h, slot_m, 0)).timestamp())
        key = (dt.date(), slot_ts)

        if key not in groups:
            groups[key] = {
                "t": slot_ts,
                "o": cd["o"],
                "h": cd["h"],
                "l": cd["l"],
                "c": cd["c"],
                "v": cd["v"],
                "buy_v": cd.get("buy_v", 0.0),
                "sell_v": cd.get("sell_v", 0.0),
            }
        else:
            groups[key]["h"] = max(groups[key]["h"], cd["h"])
            groups[key]["l"] = min(groups[key]["l"], cd["l"])
            groups[key]["c"] = cd["c"]
            groups[key]["v"] += cd["v"]
            groups[key]["buy_v"] += cd.get("buy_v", 0.0)
            groups[key]["sell_v"] += cd.get("sell_v", 0.0)
    return list(groups.values())


def split_bar_volume(c):
    """틱 데이터 부재를 보완하기 위한 위크-바디(Wick-Body) 볼륨 정밀 분배 알고리즘"""
    v, o, h, l, cl = c["v"], c["o"], c["h"], c["l"], c["c"]
    if v <= 0:
        return 0.0, 0.0
    
    rng = h - l
    if rng <= 1e-9:
        return (v * 0.5, v * 0.5)

    body_top = max(o, cl)
    body_bot = min(o, cl)
    body_size = body_top - body_bot
    upper_wick = h - body_top
    lower_wick = body_bot - l

    if cl >= o:
        buy_power = lower_wick + body_size + (upper_wick * 0.2)
        sell_power = upper_wick * 0.8
    else:
        buy_power = lower_wick * 0.8
        sell_power = upper_wick + body_size + (lower_wick * 0.2)

    total_power = buy_power + sell_power
    if total_power <= 0:
        buy_ratio = 0.5
    else:
        buy_ratio = buy_power / total_power

    buy_ratio = max(0.05, min(0.95, buy_ratio))
    
    return v * buy_ratio, v * (1.0 - buy_ratio)

def get_base_candles(token, ssym, freq, days):
    def load():
        if not token or not ssym:
            return None
        cs = schwab_candles(token, ssym, freq, days)
        if not cs:
            return None
        for c in cs:
            bv, sv = split_bar_volume(c)
            c["buy_v"] = bv
            c["sell_v"] = sv
        return cs

    return cached(f"base_candles:{ssym}:{freq}:{days}", 5, load)


def get_candles(token, inst, tf):
    key = normalize_tf(tf)

    def load():
        s_freq, s_days, agg = TF_SPEC[key]
        ssym = INSTR.get(inst)
        base = get_base_candles(token, ssym, s_freq, s_days)
        if not base:
            return None
        cs = aggregate_candles(base, agg) if agg else [dict(c) for c in base]
        return {"candles": cs, "source": f"{SRC_SCHWAB} ({ssym} {TF_LABEL[key]})"}

    return cached(f"candles:{inst}:{key}", 4, load)


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
    if is_rth and today in sessions:
        return sessions[today], False, today.strftime("%m/%d")
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
        v = c["v"]
        # 1분봉에서 누적된 실제 매수/매도 볼륨을 그대로 합산하여 전 타임프레임(1m~1H) 매도 볼륨이 0이 되는 현상 해결
        if "buy_v" in c and "sell_v" in c and (c["buy_v"] + c["sell_v"]) > 0:
            b_v, s_v = c["buy_v"], c["sell_v"]
        else:
            b_v, s_v = split_bar_volume(c)

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


# ─────────────────────────────────────────────────────────────
# 0DTE Credit Spread Optimizer 계산 엔진
# ─────────────────────────────────────────────────────────────
def compute_spread_optimizer(contracts, spot, call_wall, put_wall, em_pt):
    if not spot:
        return None

    cw = float(call_wall) if call_wall else (spot + 30.0)
    pw = float(put_wall) if put_wall else (spot - 30.0)
    em = float(em_pt) if em_pt else 25.0

    c_bound = max(cw, spot + em)
    p_bound = min(pw, spot - em)
    width = 10.0

    # 1. 행사가별 실제 매수(Bid)·매도(Ask) 호가 및 유동성 맵 구성
    quote_map = {}
    if contracts:
        for c in contracts:
            try:
                side_raw = str(c.get("type") or c.get("putCall") or c.get("side") or "").upper()
                side = "C" if side_raw.startswith("C") else ("P" if side_raw.startswith("P") else "")
                k = float(c.get("strike") or 0)
                if not side or k <= 0:
                    continue

                bid = float(c.get("bid") or 0.0)
                ask = float(c.get("ask") or 0.0)
                mid = round((bid + ask) / 2.0, 2) if (bid > 0 and ask > 0) else float(c.get("mid") or c.get("mark") or c.get("last") or 0.0)
                ba_spread = round(max(0.0, ask - bid), 2) if (bid > 0 and ask > 0) else 99.0
                vol = int(c.get("volume") or c.get("totalVolume") or 0)
                oi = int(c.get("open_interest") or c.get("openInterest") or 0)

                quote_map[(side, round(k, 1))] = {
                    "bid": bid, "ask": ask, "mid": mid,
                    "spread": ba_spread, "liq": vol + oi
                }
            except Exception:
                continue

    def _eval_spread(side, s_k, l_k, bound_val):
        qs = quote_map.get((side, round(s_k, 1)))
        ql = quote_map.get((side, round(l_k, 1)))
        dist_bound = round((s_k - bound_val) if side == "C" else (bound_val - s_k), 1)
        dist_spot = round(abs(s_k - spot), 1)

        if not qs or not ql or (qs["bid"] <= 0 and qs["mid"] <= 0):
            return None

        # 실제 매수·매도 호가 기반 체결가 계산
        # Natural(즉시 체결가) = 매도레그 Bid - 매수레그 Ask
        nat_cr = round(qs["bid"] - ql["ask"], 2) if (qs["bid"] > 0 and ql["ask"] > 0) else None
        mid_cr = round(qs["mid"] - ql["mid"], 2) if (qs["mid"] > 0 and ql["mid"] > 0) else None
        leg_spread_sum = round(qs["spread"] + ql["spread"], 2)

        # 실전 체결 예상 크레딧(Fill Credit): Mid에서 호가 슬리피지(25%) 차감, 목표 크레딧 하드코딩 배제
        if nat_cr is not None and mid_cr is not None:
            fill_cr = round(max(nat_cr, mid_cr - leg_spread_sum * 0.25), 2)
        else:
            fill_cr = mid_cr if (mid_cr and mid_cr > 0) else nat_cr

        if fill_cr is None or fill_cr <= 0.15 or fill_cr >= width * 0.90:
            return None

        # 최대 손실(Max Loss) 및 손익분기점(BEP) 정밀 계산
        max_loss_pt = round(width - fill_cr, 2)
        max_loss_usd = int(round(max_loss_pt * 100))
        max_profit_usd = int(round(fill_cr * 100))
        bep = round(s_k + fill_cr, 2) if side == "C" else round(s_k - fill_cr, 2)
        ror_pct = round((fill_cr / max_loss_pt) * 100, 1) if max_loss_pt > 0 else 0.0

        # 호가 기반 실제 체결 가능성(Fill Feasibility) 판정
        slip_ratio = leg_spread_sum / max(fill_cr, 0.01)
        if qs["bid"] <= 0.05 or leg_spread_sum > 2.50:
            fill_status = "LOW_LIQ"
            badge = f"⚠️ 호가 공백 · 체결 주의 (BEP {bep:.1f})"
        elif nat_cr is not None and nat_cr >= 0.25 and slip_ratio <= 0.45:
            fill_status = "SWEET_SPOT"
            badge = f"✅ 즉시 체결 양호 · BEP {bep:.1f} · 최대손실 -${max_loss_usd}"
        elif slip_ratio <= 0.85:
            fill_status = "LIMIT_OK"
            badge = f"🟢 지정가 체결 가능 · BEP {bep:.1f} · 최대손실 -${max_loss_usd}"
        else:
            fill_status = "WIDE_SPREAD"
            badge = f"🟡 호가 벌어짐(슬리피지 주의) · BEP {bep:.1f}"

        nat_str = f"${nat_cr:.2f}" if nat_cr is not None and nat_cr > 0 else "불가"
        guide = (
            f"실제호가(매도Bid ${qs['bid']:.2f}/매수Ask ${ql['ask']:.2f}) · "
            f"즉시체결 {nat_str} / 예상체결 ${fill_cr:.2f}(+${max_profit_usd}) · "
            f"최대손실 -${max_loss_usd}(RoR {ror_pct:.1f}%) · 손익분기 {bep:.1f}"
        )

        # 점수 산정: 목표 크레딧 고정 없이 [체결 용이성 + 안전 마진 + 손익비 균형]으로 평가
        liq_score = 30.0 if fill_status == "SWEET_SPOT" else (20.0 if fill_status == "LIMIT_OK" else 5.0)
        safety_score = min(25.0, max(0.0, dist_bound * 1.5)) + (15.0 if dist_bound >= 0 else -20.0)
        ror_score = max(0.0, 20.0 - abs(ror_pct - 15.0) * 0.6)
        score = liq_score + safety_score + ror_score

        return {
            "short": s_k, "long": l_k, "credit": fill_cr,
            "nat_credit": nat_cr, "mid_credit": mid_cr,
            "max_loss": max_loss_pt, "max_loss_usd": max_loss_usd,
            "max_profit_usd": max_profit_usd, "bep": bep, "ror_pct": ror_pct,
            "short_bid": qs["bid"], "long_ask": ql["ask"], "ba_spread": leg_spread_sum,
            "dist_spot": dist_spot, "dist_bound": dist_bound,
            "status": fill_status, "badge": badge, "guide": guide,
            "boundary": round(bound_val, 1), "_score": score
        }

    # 2. 안전선(c_bound / p_bound) 바깥 행사가 후보군 탐색 (5pt 단위)
    min_short_c = float(int((c_bound + 4.99) // 5) * 5)
    max_short_p = float(int(p_bound // 5) * 5)

    call_candidates = []
    put_candidates = []
    for i in range(8):
        sc = min_short_c + (i * 5.0)
        res_c = _eval_spread("C", sc, sc + width, c_bound)
        if res_c:
            call_candidates.append(res_c)

        sp = max_short_p - (i * 5.0)
        res_p = _eval_spread("P", sp, sp - width, p_bound)
        if res_p:
            put_candidates.append(res_p)

    best_c = max(call_candidates, key=lambda x: x["_score"]) if call_candidates else None
    best_p = max(put_candidates, key=lambda x: x["_score"]) if put_candidates else None

    if not best_c:
        bep_fallback_c = round(min_short_c, 1)
        best_c = {
            "short": min_short_c, "long": min_short_c + width, "credit": None,
            "max_loss": None, "max_loss_usd": None, "bep": bep_fallback_c,
            "status": "WAITING", "badge": f"장중 호가 대기 · 기준선 {min_short_c:.0f}",
            "guide": f"안전선({c_bound:.0f}) 바깥 {width:.0f}pt 폭 · 정규장 개장 후 매수·매도 호가 유입 시 최대손실·BEP 자동 산출",
            "boundary": round(c_bound, 1)
        }
    else:
        best_c.pop("_score", None)

    if not best_p:
        bep_fallback_p = round(max_short_p, 1)
        best_p = {
            "short": max_short_p, "long": max_short_p - width, "credit": None,
            "max_loss": None, "max_loss_usd": None, "bep": bep_fallback_p,
            "status": "WAITING", "badge": f"장중 호가 대기 · 기준선 {max_short_p:.0f}",
            "guide": f"안전선({p_bound:.0f}) 바깥 {width:.0f}pt 폭 · 정규장 개장 후 매수·매도 호가 유입 시 최대손실·BEP 자동 산출",
            "boundary": round(p_bound, 1)
        }
    else:
        best_p.pop("_score", None)

    return {
        "available": True,
        "width": int(width),
        "engine_policy": "실제 매수·매도 호가로 체결 가능성을 검토하고, 최대 손실과 손익분기점을 계산합니다. 목표 크레딧만으로 추천하지 않습니다.",
        "call_spread": best_c,
        "put_spread": best_p,
    }
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
        c_gex_val = round(e["call_gex"] / 1e6, 2)
        p_gex_val = round(abs(e["put_gex"]) / 1e6, 2)
        net_gex_m = round((e["call_gex"] + e["put_gex"]) / 1e6, 2)
        abs_gex_m = round(abs(c_gex_val) + p_gex_val, 1)

        by_strike.append({
            "strike": round(K * scale, 1),
            "call_oi": int(e["call_oi"]),
            "put_oi": int(e["put_oi"]),
            "call_vol": int(e["call_vol"]),
            "put_vol": int(e["put_vol"]),
            "call_gex_m": c_gex_val,
            "put_gex_m": p_gex_val,
            "net_gex_m": net_gex_m,
            "abs_gex_m": abs_gex_m,
        })

    abs_pin_strike = None
    abs_pin_val = 0.0
    if by_strike:
        top_pin = max(by_strike, key=lambda s: s.get("abs_gex_m", 0))
        abs_pin_strike = top_pin["strike"]
        abs_pin_val = top_pin["abs_gex_m"]
    is_0dte_session = bool((now_et.hour < 16 and exp_date == now_et.date().isoformat()) or (now_et.hour >= 16 and exp_date >= now_et.date().isoformat()))

   # --- 실제 SPX Gamma Flip (Zero-Gamma 변곡점) 정밀 계산 ---
    real_gamma_flip = None
    gamma_flip_note = None
    try:
        valid_strikes = sorted(
            [s for s in by_strike if s.get("strike") is not None],
            key=lambda x: float(x["strike"])
        )
        if spot and len(valid_strikes) >= 4:
            near_strikes = [s for s in valid_strikes if abs(float(s["strike"]) - spot) <= 150]
            if len(near_strikes) >= 4:
                valid_strikes = near_strikes

        if len(valid_strikes) >= 2:
            # 1) 개별 행사가 노이즈 완화를 위한 3-Strike 스무딩 Net GEX 산출
            n_st = len(valid_strikes)
            smoothed_gex = []
            for idx in range(n_st):
                win = valid_strikes[max(0, idx - 1):min(n_st, idx + 2)]
                avg_net = sum(float(x.get("net_gex_m", x.get("net_gex", 0.0))) for x in win) / len(win)
                smoothed_gex.append((float(valid_strikes[idx]["strike"]), avg_net))

            # 2) 음(-)에서 양(+)으로 감마가 뒤집히는 영교차점(Zero-Crossing) 선형 보간
            crossings = []
            for idx in range(len(smoothed_gex) - 1):
                k1, g1 = smoothed_gex[idx]
                k2, g2 = smoothed_gex[idx + 1]
                if g1 == 0:
                    crossings.append((round(k1, 1), g2 > 0))
                elif (g1 < 0 and g2 > 0) or (g1 > 0 and g2 < 0):
                    flip_pt = k1 + (k2 - k1) * (0.0 - g1) / (g2 - g1)
                    crossings.append((round(flip_pt, 1), g1 < 0 and g2 > 0))

            if crossings:
                # 음(-) -> 양(+) 정방향 변곡점 우선, 현재가(spot)에서 가장 가까운 지점 선택
                pos_crossings = [c[0] for c in crossings if c[1]]
                candidates = pos_crossings if pos_crossings else [c[0] for c in crossings]
                real_gamma_flip = min(candidates, key=lambda x: abs(x - spot)) if spot else candidates[0]
                gamma_flip_note = "Zero-GEX 선형보간 (실시간 체인)"
            else:
                # 3) 전 구간 단일 부호 편향 장세일 때: Call/Put 감마 가중 힘의 균형점 산출
                t_call = sum(abs(float(s.get("call_gex_m", s.get("call_gex", 0.0)))) for s in valid_strikes)
                t_put = sum(abs(float(s.get("put_gex_m", s.get("put_gex", 0.0)))) for s in valid_strikes)
                if t_call > 0 and t_put > 0:
                    c_center = sum(float(s["strike"]) * abs(float(s.get("call_gex_m", s.get("call_gex", 0.0)))) for s in valid_strikes) / t_call
                    p_center = sum(float(s["strike"]) * abs(float(s.get("put_gex_m", s.get("put_gex", 0.0)))) for s in valid_strikes) / t_put
                    w_put = t_put / (t_call + t_put)
                    real_gamma_flip = round(c_center * w_put + p_center * (1.0 - w_put), 1)
                    gamma_flip_note = "Call/Put 감마 가중 균형점"
    except Exception:
        real_gamma_flip = None

    if real_gamma_flip is None:
        real_gamma_flip = round((call_wall + put_wall) / 2.0, 1) if (call_wall and put_wall) else round(spot, 1)
        gamma_flip_note = "Wall 중간값 폴백"

    return {
        "available": True, "source": source, "expiration": exp_date, "is_0dte": is_0dte_session, "spot": round(spot, 1),
        "call_wall": round(call_wall, 1) if call_wall else None, "put_wall": round(put_wall, 1) if put_wall else None,
        "gamma_flip": real_gamma_flip, "gamma_flip_note": gamma_flip_note,
        "em_pt": round(em_pt, 1) if em_pt else None, "expected_move": f"±{em_pt:.1f}pt ({em_pt / spot * 100:.2f}%)" if em_pt else None,
        "net_gex": fmt_dollars(net_total), "regime": "positive" if net_total >= 0 else "negative",
        "regime_text": "양(+) 감마 우세 - 딜러 헤지가 변동성 억제" if net_total >= 0 else "음(−) 감마 우세 - 변동성 증폭 구간",
        "strike_count": len(per), "by_strike": by_strike,
        "abs_pin_strike": abs_pin_strike,
        "abs_pin_val": abs_pin_val,
        "gamma_source_note": f"감마 {gamma_schwab}개 Schwab 제공값, {gamma_calc}개 BS 실시간 계산값",
        "oi_skew": {
            "call_oi_at_or_above_spot": int(sum(e["call_oi"] for k, e in per.items() if k >= S)),
            "put_oi_at_or_above_spot": int(sum(e["put_oi"] for k, e in per.items() if k >= S)),
            "call_oi_below_spot": int(sum(e["call_oi"] for k, e in per.items() if k < S)),
            "put_oi_below_spot": int(sum(e["put_oi"] for k, e in per.items() if k < S)),
            "spread_optimizer": compute_spread_optimizer(contracts, spot, call_wall, put_wall, em_pt),
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
    is_pre_alert = False

    if len(recent_bars) >= 2 and ratio:
        curr_c = recent_bars[-1]["c"] * ratio
        net_15m = curr_c - (recent_bars[-3]["o"] * ratio if len(recent_bars) >= 3 else recent_bars[0]["o"] * ratio)
        fast_5m = curr_c - (recent_bars[-2]["c"] * ratio)

        if fast_5m <= -10.0 or net_15m <= -16.0:
            shock_type = "DROP"
            level = "CRITICAL" if (fast_5m <= -15.0 or net_15m <= -24.0) else "WARNING"
            val = fast_5m if fast_5m <= -10.0 else net_15m
            reasons.append(f"단기 급락 압력 발생 ({val:.1f}pt 하락)")

        elif fast_5m >= 10.0 or net_15m >= 16.0:
            shock_type = "SURGE"
            level = "CRITICAL" if (fast_5m >= 15.0 or net_15m >= 24.0) else "WARNING"
            val = fast_5m if fast_5m >= 10.0 else net_15m
            reasons.append(f"단기 급등 모멘텀 발생 (+{val:.1f}pt 상승)")

    if gex and gex.get("available") and gex.get("is_0dte"):
        pw, cw = gex.get("put_wall"), gex.get("call_wall")
        by_strike = gex.get("by_strike", [])
        BUFFER = 2.5

        if pw and spx_p < (pw - BUFFER):
            reasons.append(f"Put Wall 지지선({pw:.1f}) 하향 붕괴 이탈 ({spx_p - pw:.1f}pt)")
            shock_type, level = "DROP", "CRITICAL"

        elif cw and spx_p > (cw + BUFFER):
            reasons.append(f"Call Wall 저항선({cw:.1f}) 상향 돌파 이탈 (+{spx_p - cw:.1f}pt)")
            shock_type, level = "SURGE", "CRITICAL"

        elif cw and (cw - 10.0 <= spx_p <= cw + BUFFER):
            cw_row = next((s for s in by_strike if abs(s["strike"] - cw) < 1.0), None)
            if cw_row:
                c_vol, c_oi = cw_row.get("call_vol", 0), cw_row.get("call_oi", 0)
                net_gex_m = cw_row.get("net_gex_m", 0)
                vol_threat = (c_oi > 0 and c_vol >= c_oi * 1.5) or (c_vol >= 8000)
                short_gamma = (net_gex_m < 0)
                cvd_bullish = (cvd and not cvd.get("is_prior") and cvd.get("buy_pct", 0) >= 54)

                if (vol_threat or short_gamma) and cvd_bullish:
                    shock_type, level = "SURGE", "CRITICAL"
                    is_pre_alert = True
                    reasons.append(f"Call Wall({cw:.0f}) 돌파 임박 접근 (현재 {spx_p:.1f}, 이격 {cw - spx_p:.1f}pt)")
                    if vol_threat:
                        reasons.append(f"{cw:.0f} Call 거래량({c_vol:,})이 미결제({c_oi:,}) 대비 폭발 (신규 매수벽 공격)")
                    if short_gamma:
                        reasons.append(f"{cw:.0f} Net GEX 음수({net_gex_m}M$)로 딜러 숏 감마 스퀴즈 가속")
                    reasons.append("⚠️ Bear Call Spread 신규 진입 즉시 보류")

        elif pw and (pw - BUFFER <= spx_p <= pw + 10.0):
            pw_row = next((s for s in by_strike if abs(s["strike"] - pw) < 1.0), None)
            if pw_row:
                p_vol, p_oi = pw_row.get("put_vol", 0), pw_row.get("put_oi", 0)
                vol_threat = (p_oi > 0 and p_vol >= p_oi * 1.5) or (p_vol >= 8000)
                cvd_bearish = (cvd and not cvd.get("is_prior") and cvd.get("sell_pct", 0) >= 54)

                if vol_threat and cvd_bearish:
                    shock_type, level = "DROP", "CRITICAL"
                    is_pre_alert = True
                    reasons.append(f"Put Wall({pw:.0f}) 지지선 붕괴 임박 접근 (현재 {spx_p:.1f}, 이격 {spx_p - pw:.1f}pt)")
                    reasons.append(f"{pw:.0f} Put 거래량({p_vol:,})이 미결제({p_oi:,}) 대비 폭발 (지지선 이탈 위험)")
                    reasons.append("⚠️ Bull Put Spread 신규 진입 즉시 보류")

        if not is_pre_alert:
            if shock_type == "SURGE" and pw and spx_p <= pw + 4.0:
                return {"active": False}
            if shock_type == "DROP" and cw and spx_p >= cw - 4.0:
                return {"active": False}

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

    if is_pre_alert:
        title = "🚨 [감마 스퀴즈 경보] Call Wall 돌파 임박" if shock_type == "SURGE" else "🚨 [감마 플러시 경보] Put Wall 붕괴 임박"
    else:
        title = (
            "🚨 [변동성 쇼크 · 급락 경보]"
            if shock_type == "DROP" and level == "CRITICAL"
            else (
                "⚠️ [변동성 쇼크 · 하방 주의보]"
                if shock_type == "DROP"
                else ("🚀 [변동성 쇼크 · 급등 경보]" if level == "CRITICAL" else "⚡ [변동성 쇼크 · 상방 모멘텀]")
            )
        )

    return {
        "active": is_active,
        "type": shock_type,
        "level": level,
        "title": title,
        "elapsed_text": elapsed_text or now_et.strftime("%H:%M ET"),
        "details": reasons,
        "timestamp": now_et.strftime("%H:%M:%S ET"),
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
    label, tone = (
        ("상승 우세", "bull")
        if score >= 3.0
        else (
            ("상승 편향", "bull")
            if score >= 1.2
            else (("중립", "flat") if score > -1.2 else (("하락 편향", "bear") if score > -3.0 else ("하락 우세", "bear")))
        )
    )
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
    label, tone = (
        ("상승 우세", "bull")
        if score >= 3.0
        else (
            ("상승 편향", "bull")
            if score >= 1.2
            else (("중립", "flat") if score > -1.2 else (("하락 편향", "bear") if score > -3.0 else ("하락 우세", "bear")))
        )
    )
    match_pct = int(round(sum(1 for v in avail.values() if v["tone"] == tone) / len(avail) * 100))

    evidence = []
    if vwap_diff is not None:
        evidence.append(
            {
                "title": "VWAP 위치",
                "signal": "bull" if vwap_diff > 0 else ("bear" if vwap_diff < 0 else "flat"),
                "text": f"현재가가 당일 VWAP {'위' if vwap_diff > 0 else '아래'} ({vwap_diff:+.2f}pt)",
            }
        )
    if cvd_data:
        evidence.append(
            {
                "title": "CVD 볼륨 압력",
                "signal": cvd_data["tone"],
                "text": f"{cvd_data['status']} (Buy {cvd_data['buy_pct']}% / Sell {cvd_data['sell_pct']}%)",
            }
        )

    return {
        "available": True,
        "score": round(score, 1),
        "score_text": f"{score:+.1f}",
        "status": label,
        "tone": tone,
        "match_pct": match_pct,
        "summary": f"단기 모멘텀과 체결 압력이 {'상승' if tone=='bull' else ('하락' if tone=='bear' else '중립')} 쪽입니다. {match_pct}% 일치.",
        "tfs": {k: ({**avail[k], "source": tf_sources.get(k)} if k in avail else None) for k in ("1h", "15m", "5m", "1m")},
        "evidence": evidence,
        "source": "Charles Schwab (SPY) · 0DTE EMA(5/13/21)·VWAP·CVD 결합",
    }


# ─────────────────────────────────────────────────────────────
# API 엔드포인트
# ─────────────────────────────────────────────────────────────
@app.get("/api/test-alert")
def test_telegram_alert():
    now_et = datetime.now(ET)
    mock = {
        "active": True,
        "type": "DROP",
        "level": "CRITICAL",
        "title": "🚨 [시스템 테스트] 텔레그램 연동 정상 작동 확인",
        "timestamp": now_et.strftime("%H:%M:%S ET"),
        "elapsed_text": f"{now_et.strftime('%H:%M ET')} 테스트 발송",
        "details": ["환경변수 연동 성공", "실시간 급변동 감지 시 이와 동일하게 자동 전송됩니다."],
    }
    return {"status": "ok", "result": send_telegram_shock_alert(mock, 5750.0, force_test=True)}


@app.get("/api/refresh-token")
def refresh_token_cron():
    token, msg = get_schwab_token(force_refresh=True)
    return {"status": "ok" if token else "error", "message": msg}


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
    spy_tf_set = {"1h", "15m", "5m", "1m", c_key}

    with ThreadPoolExecutor(max_workers=10) as ex:
        f_spy_all = {k: ex.submit(get_candles, token, "spy", k) for k in spy_tf_set}
        f_spx_r = ex.submit(get_candles, token, "spx", r_key)
        f_gex = ex.submit(get_gex, token, spx_p, ratio_q, now_et)
        f_poly = ex.submit(get_polymarket_spx, spx_p)
        f_cal = ex.submit(cached, "econ_events_data", 15, fetch_global_econ_calendar)
        f_news = ex.submit(fetch_flash_market_news)

    spy_all_c = {k: f.result() for k, f in f_spy_all.items()}
    spx_r = f_spx_r.result()
    spy_c = spy_all_c.get(c_key)
    gex = f_gex.result() or {"available": False, "source": "N/A"}
    polymarket = f_poly.result()
    _ = f_cal.result()
    _ = f_news.result()

    spy_5m = spy_all_c.get("5m")
    ratio = ratio_q or ((spx_p / spy_5m["candles"][-1]["c"]) if (spx_p and spy_5m and spy_5m.get("candles")) else None)

    spy_5m_bars = spy_5m.get("candles") if spy_5m else []
    econ_events = get_today_econ_events(now_et, spy_5m_bars, ratio)

    vwap_calc = compute_vwap(spy_5m_bars, ratio, now_et) if spy_5m else None
    vp = compute_volume_profile(spy_5m_bars, ratio, spy_5m["source"], now_et) if (spy_5m and ratio) else None
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
        d = spy_all_c.get(k)
        tf_results[k] = analyze_tf(d["candles"]) if (d and d.get("candles")) else None
        tf_sources[k] = d["source"] if d else None

    c1h = spy_all_c["1h"]["candles"] if (spy_all_c.get("1h") and spy_all_c["1h"].get("candles")) else []
    direction = build_direction(tf_results, tf_sources, spx_p, vwap_calc, c1h, cvd)

    vix_target = quotes.get("vix1d") or quotes.get("vix")
    shock_alert = detect_market_shock(spx_p, spy_5m_bars, ratio, gex, cvd, vix_target, now_et)
    if shock_alert and shock_alert.get("active"):
        send_telegram_shock_alert(shock_alert, spx_p)

    def slim(q):
        return {"price": q["price"], "change": q["change"], "change_pct": q.get("change_pct"), "source": q["source"]} if q else None

    used = [q["source"] for q in quotes.values() if q]
    schwab_cnt = sum(1 for s in used if src_kind(s) == "schwab")

   # 기존 main.py 어딘가에 이 부분이 있을 것입니다.
        # 이 전체 딕셔너리를 아래 코드로 교체해 주세요!
        
        return {
            "status": "success",
            "timestamp": now_str,
            "source_summary": f"Schwab {schwab_cnt} · Realtime Hybrid",
            "schwab_status": schwab_msg,
            "shock_alert": shock_alert,
            "spx": q_spx,
            "es": quotes.get("/ES"),         # 수정: "es" -> "/ES" (Schwab 선물 심볼)
            "vix1d": slim(quotes.get("$VIX1D")), # 수정: "vix1d" -> "$VIX1D"
            "vix": slim(quotes.get("$VIX")),     # 수정: "vix" -> "$VIX"
            "mag7": quotes.get("MAGS"),      # 수정: None -> quotes.get("MAGS")
            "econ_events": econ_events,
            "wti": quotes.get("/CL"),        # 수정: "wti" -> "/CL"
            "brent": quotes.get("/BZ"),      # 수정: "brent" -> "/BZ"
            "uso": quotes.get("USO"),        # 추가: USO 데이터 반환
            "yields": {                      # 수정: None -> 실제 데이터 구조로 변경
                "3m": quotes.get("$IRX"),
                "10y": quotes.get("$TNX"),
                "30y": quotes.get("$TYX")
            },
            "polymarket": polymarket,
            "volume_profile": vp,
            "gex": gex,
            "rsi": rsi,
            "cvd": cvd,
            "direction": direction,
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
