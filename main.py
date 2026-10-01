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
import xml.etree.ElementTree as XET
from email.utils import parsedate_to_datetime
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
    """Upstash/Vercel KV REST 단일 명령 실행. 연결 안 돼 있거나 실패하면 None."""
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
# 뉴스 및 중요 발표
# ─────────────────────────────────────────────────────────────
NEWS_TAG_RULES = [
    ("FED", ("federal reserve", "fomc", "powell", " fed ", "fed's", "fed rate", "rate cut", "rate hike",
              "rate decision", "central bank", "quantitative", "interest rate")),
    ("INFLATION", ("inflation", "cpi", "pce", "core prices", "consumer prices", "producer price")),
    ("JOBS", ("jobs report", "payrolls", "unemployment", "nonfarm", "jobless claims", "jolts",
               "job openings", "labor market", "hiring")),
    ("MACRO", ("gdp", "ism ", "pmi ", "retail sales", "consumer confidence", "consumer sentiment",
                "housing starts", "industrial production", "durable goods")),
    ("EARNINGS", ("earnings", "guidance", "quarterly results", "profit warning", "beats estimates",
                   "misses estimates")),
    ("GEOPOLITICS", ("tariff", "sanctions", " war ", "conflict", "geopolit", "opec", " china ", "trade deal")),
    ("YIELDS", ("treasury yield", "bond yield", "yields ", "10-year", "2-year")),
    ("VOLATILITY", ("volatility", "vix", "selloff", "sell-off", "plunge", "rally", "swings", "record high",
                     "correction", "crash", "circuit breaker")),
    ("POLICY", ("sec ", "antitrust", "shutdown", "debt ceiling", "stimulus", "regulation", "white house",
                 "executive order")),
]


def tag_news(title):
    t = f" {title.lower()} "
    return [name for name, kws in NEWS_TAG_RULES if any(k in t for k in kws)]


BLS_TITLE_KR = {
    "Employment Situation": "고용보고서 (비농업고용, NFP)",
    "Consumer Price Index": "소비자물가지수 (CPI)",
    "Producer Price Index": "생산자물가지수 (PPI)",
    "Job Openings and Labor Turnover Survey": "구인이직보고서 (JOLTS)",
    "Employment Cost Index": "고용비용지수 (ECI)",
    "Productivity and Costs": "생산성 및 단위노동비용",
    "U.S. Import and Export Price Indexes": "수출입물가지수",
}
HIGH_IMPACT_BLS_TITLES = set(BLS_TITLE_KR)
BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
_BLS_CAL_CACHE = {"attempt_ts": 0.0, "events": None, "error": None}
BLS_CAL_RETRY_SEC = 300
BLS_CAL_REFRESH_SEC = 6 * 3600


def _parse_ics_events(text):
    events, cur = [], {}
    for raw in text.splitlines():
        line = raw.strip()
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if "summary" in cur and "dt" in cur:
                events.append(cur)
            cur = {}
        elif line.startswith("SUMMARY:"):
            cur["summary"] = line[len("SUMMARY:"):].strip()
        elif line.startswith("DTSTART"):
            try:
                val = line.split(":", 1)[1].strip()
                naive = datetime.strptime(val.replace("Z", ""), "%Y%m%dT%H%M%S")
                cur["dt"] = naive.replace(tzinfo=pytz.UTC).astimezone(ET) if val.endswith("Z") else ET.localize(naive)
            except Exception:
                pass
    return events


def fetch_bls_calendar():
    now = time.time()
    stale_after = BLS_CAL_RETRY_SEC if _BLS_CAL_CACHE["events"] is None else BLS_CAL_REFRESH_SEC
    if now - _BLS_CAL_CACHE["attempt_ts"] < stale_after:
        return _BLS_CAL_CACHE["events"], _BLS_CAL_CACHE["error"]
    _BLS_CAL_CACHE["attempt_ts"] = now
    try:
        r = requests.get(BLS_ICS_URL, headers=HEADERS, timeout=4)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        if len(r.text) > 3_000_000:
            raise RuntimeError("응답이 너무 큼")
        _BLS_CAL_CACHE["events"] = _parse_ics_events(r.text)
        _BLS_CAL_CACHE["error"] = None
    except Exception as e:
        _BLS_CAL_CACHE["error"] = f"{type(e).__name__}: {e}"
    return _BLS_CAL_CACHE["events"], _BLS_CAL_CACHE["error"]


def get_today_econ_events(now_et):
    events, err = fetch_bls_calendar()
    if events is None:
        return {"items": [], "source": "N/A", "error": err or "BLS 캘린더를 가져오지 못했습니다"}
    today = now_et.date()
    now_ts = now_et.timestamp()
    items = []
    for e in events:
        if e["dt"].date() != today or e["summary"] not in HIGH_IMPACT_BLS_TITLES:
            continue
        items.append({
            "title": BLS_TITLE_KR.get(e["summary"], e["summary"]),
            "title_en": e["summary"],
            "time": e["dt"].strftime("%H:%M ET"),
            "ts": e["dt"].timestamp(),
            "passed": e["dt"].timestamp() < now_ts,
        })
    items.sort(key=lambda x: x["ts"])
    return {"items": items, "source": "BLS 공식 일정 (bls.gov)", "error": None}


def relative_time_label(ts, now_ts):
    if not ts:
        return None
    delta = now_ts - ts
    if delta < 0:
        delta = 0
    if delta < 60:
        return "방금"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


NEWS_MAX_CHARS = 1_500_000
NEWS_MAX_AGE_SEC = 48 * 3600
_NEWS_CACHE = {"ts": 0.0, "items": [], "diag": []}


def _news_http(url, params=None):
    r = requests.get(
        url,
        headers={**HEADERS, "Accept": "application/rss+xml, application/xml, text/xml, application/json, */*"},
        params=params,
        timeout=3.5,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    if len(r.text) > NEWS_MAX_CHARS:
        raise RuntimeError("응답이 너무 큼")
    return r


def _parse_rss(text, default_publisher, split_publisher=False):
    root = XET.fromstring(text)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        ts = None
        pub = item.findtext("pubDate")
        if pub:
            try:
                ts = parsedate_to_datetime(pub).timestamp()
            except Exception:
                ts = None
        publisher = default_publisher
        src_el = item.find("source")
        if src_el is not None and (src_el.text or "").strip():
            publisher = src_el.text.strip()
        if split_publisher and " - " in title:
            head, _, tail = title.rpartition(" - ")
            if head and 0 < len(tail) <= 40:
                title, publisher = head.strip(), tail.strip()
        if title and link.lower().startswith(("http://", "https://")):
            out.append({"title": title, "link": link, "publisher": publisher, "ts": ts})
    return out


def _news_yahoo_search():
    last_err = None
    for host in ("query2", "query1"):
        try:
            r = _news_http(
                f"https://{host}.finance.yahoo.com/v1/finance/search",
                {"q": "S&P 500 stock market", "newsCount": 10, "quotesCount": 0, "lang": "en-US"},
            )
            out = []
            for n in r.json().get("news") or []:
                title, link = n.get("title"), n.get("link")
                if title and link and str(link).lower().startswith(("http://", "https://")):
                    out.append({"title": title, "link": link, "publisher": n.get("publisher") or "Yahoo Finance",
                                "ts": num(n.get("providerPublishTime"))})
            if out:
                return out
            last_err = "뉴스 0건"
        except Exception as e:
            last_err = str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}"
    raise RuntimeError(last_err or "실패")


def _news_yahoo_rss():
    r = _news_http("https://feeds.finance.yahoo.com/rss/2.0/headline",
                   {"s": "^GSPC,SPY,^VIX", "region": "US", "lang": "en-US"})
    return _parse_rss(r.text, "Yahoo Finance")


def _news_google_rss():
    r = _news_http("https://news.google.com/rss/search",
                   {"q": "(S&P 500 OR Wall Street OR Federal Reserve OR inflation) when:1d",
                    "hl": "en-US", "gl": "US", "ceid": "US:en"})
    return _parse_rss(r.text, "Google News", split_publisher=True)


def _news_cnbc_rss():
    r = _news_http("https://search.cnbc.com/rs/search/combinedcms/view.xml",
                   {"partnerId": "wrss01", "id": "10000664"})
    return _parse_rss(r.text, "CNBC")


NEWS_SOURCES = [
    ("Yahoo 검색", _news_yahoo_search),
    ("Yahoo RSS", _news_yahoo_rss),
    ("Google News", _news_google_rss),
    ("CNBC", _news_cnbc_rss),
]


def _norm_title(t):
    return "".join(ch for ch in t.lower() if ch.isalnum())[:60]


def fetch_market_news(now_ts=None):
    now = time.time()
    ttl = 60 if _NEWS_CACHE["items"] else 20
    if _NEWS_CACHE["ts"] and now - _NEWS_CACHE["ts"] < ttl:
        return _NEWS_CACHE["items"], _NEWS_CACHE["diag"]

    def run(src):
        name, fn = src
        try:
            items = fn()
            return name, items, None
        except Exception as e:
            return name, None, (str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}")[:120]

    with ThreadPoolExecutor(max_workers=len(NEWS_SOURCES)) as ex:
        results = list(ex.map(run, NEWS_SOURCES))

    diag, merged, seen = [], [], set()
    for name, items, err in results:
        if err:
            diag.append({"source": name, "ok": False, "error": err})
            continue
        diag.append({"source": name, "ok": True, "count": len(items)})
        for it in items:
            key = _norm_title(it["title"])
            if not key or key in seen:
                continue
            seen.add(key)
            it["from"] = name
            it["tags"] = tag_news(it["title"])
            merged.append(it)

    important = [x for x in merged if x["tags"]]
    pool = important if len(important) >= 3 else merged

    pool.sort(key=lambda x: x["ts"] or 0, reverse=True)
    ref_ts = now_ts if now_ts is not None else now
    fresh = [x for x in pool if x["ts"] and ref_ts - x["ts"] <= NEWS_MAX_AGE_SEC]
    items = fresh if len(fresh) >= 3 else pool
    _NEWS_CACHE.update(ts=now, items=items[:10], diag=diag)
    return _NEWS_CACHE["items"], diag


def get_news(now_et):
    now_ts = now_et.timestamp()
    items, diag = fetch_market_news(now_ts)
    out_items = [{
        "title": it["title"],
        "link": it["link"],
        "publisher": it["publisher"],
        "time_label": relative_time_label(it["ts"], now_ts),
        "tags": it["tags"],
    } for it in items[:6]]
    all_tags = []
    for it in out_items:
        for tag in it["tags"]:
            if tag not in all_tags:
                all_tags.append(tag)
    used = [d["source"] for d in diag if d["ok"] and d.get("count")]
    return {
        "items": out_items,
        "tags": all_tags[:5],
        "source": " + ".join(used) if used else "N/A",
        "diag": diag,
    }


# ─────────────────────────────────────────────────────────────
# 봉(candle) 데이터 (Schwab pricehistory 우선 -> Yahoo chart)
# ─────────────────────────────────────────────────────────────
# 10m은 5분봉 2개를 정규장(09:30) 기준으로 합쳐서 완벽히 산출합니다.
TF_SPEC = {
    "1m": ("1m", "2d", 1, 2, None),
    "5m": ("5m", "5d", 5, 5, None),
    "10m": ("5m", "5d", 5, 5, 10),
    "15m": ("15m", "5d", 15, 5, None),
    "30m": ("30m", "5d", 30, 5, None),
    "1h": ("60m", "1mo", 30, 10, 60),
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
    """분봉을 미국 정규장 시작(09:30 ET = 570분) 기준으로 minutes 단위 봉으로 정확히 합칩니다.
    10분봉일 경우 15:50~16:00 이 단독 1개 봉으로 완벽히 분리됩니다.
    """
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


def get_rth_session(candles):
    """당일 미국 정규장(09:30 ET ~ 16:00 ET 또는 현재) 봉만 추출합니다."""
    if not candles:
        return []
    last_dt = datetime.fromtimestamp(candles[-1]["t"], ET)
    target_date = last_dt.date()
    open_ts = int(ET.localize(datetime(target_date.year, target_date.month, target_date.day, 9, 30, 0)).timestamp())
    close_ts = int(ET.localize(datetime(target_date.year, target_date.month, target_date.day, 16, 0, 0)).timestamp())

    rth_bars = [c for c in candles if open_ts <= c["t"] <= close_ts]
    if rth_bars:
        return rth_bars

    all_dates = sorted(list({datetime.fromtimestamp(c["t"], ET).date() for c in candles}), reverse=True)
    for d in all_dates:
        d_open = int(ET.localize(datetime(d.year, d.month, d.day, 9, 30, 0)).timestamp())
        d_close = int(ET.localize(datetime(d.year, d.month, d.day, 16, 0, 0)).timestamp())
        d_bars = [c for c in candles if d_open <= c["t"] <= d_close]
        if d_bars:
            return d_bars

    return [c for c in candles if datetime.fromtimestamp(c["t"], ET).date() == target_date]


def last_session(candles):
    return get_rth_session(candles)


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
# VWAP / Volume Profile / CVD (A/D Pressure Model, 09:30~ Session)
# ─────────────────────────────────────────────────────────────
def compute_vwap(spy_candles, ratio, source):
    sess = get_rth_session(spy_candles)
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
        "source": f"{source} x SPX/SPY 환산 · 당일 정규장 VWAP · 밴드=거래량가중 표준편차",
    }


def last_rth_close(spx_candles):
    if not spx_candles:
        return None
    last_date = datetime.fromtimestamp(spx_candles[-1]["t"], ET).date()
    today = datetime.now(ET).date()
    if last_date < today:
        return spx_candles[-1]
    prior = [c for c in spx_candles if datetime.fromtimestamp(c["t"], ET).date() < today]
    return prior[-1] if prior else None


VP_WINDOW_HOURS = 24
BASIS_MAX_GAP_SEC = 20 * 60


def compute_volume_profile(es_candles, spx_candles, es_source, spx_source):
    anchor = last_rth_close(spx_candles)
    if not anchor or not es_candles:
        return None
    es_at_anchor = min(es_candles, key=lambda c: abs(c["t"] - anchor["t"]))
    if abs(es_at_anchor["t"] - anchor["t"]) > BASIS_MAX_GAP_SEC:
        return None
    basis = anchor["c"] - es_at_anchor["c"]

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


def compute_cvd(candles, tf_key, source, symbol="SPY"):
    """모든 타임프레임(1m, 5m, 10m, 15m, 30m, 1H)에서 당일 정규장(09:30 ET ~ 현재)을
    온전히 집계하는 A/D 압력 CVD 모델입니다.
    """
    if not candles:
        return None
    tf_label = TF_LABEL.get(tf_key, tf_key)

    bars = get_rth_session(candles)
    if not bars:
        return None

    buy = sell = running = 0.0
    out = []
    for c in bars:
        v = c["v"]
        h, l, cl = c["h"], c["l"], c["c"]
        rng = h - l
        
        # 캔들 내 종가 압력(Volume Fraction) 분할
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
        text = f"Strong buying pressure – {buy_pct}% buy volume in regular session."
    elif buy_pct >= 53:
        status, tone = "Buying Pressure", "bull"
        text = f"Moderate buying pressure – {buy_pct}% buy volume in regular session."
    elif buy_pct > 47:
        status, tone = "Balanced", "flat"
        text = f"Balanced flow – buy {buy_pct}% / sell {sell_pct}% in regular session."
    elif buy_pct > 40:
        status, tone = "Selling Pressure", "bear"
        text = f"Moderate selling pressure – {sell_pct}% sell volume in regular session."
    else:
        status, tone = "Selling Pressure", "bear"
        text = f"Strong selling pressure – {sell_pct}% sell volume in regular session."

    start_ts, end_ts = bars[0]["t"], bars[-1]["t"]
    sess_date = datetime.fromtimestamp(end_ts, ET).strftime("%m/%d")
    aggregate_range = f"{sess_date} 정규장 (09:30 ~ {et_time_sec(end_ts)}) · {len(bars)}개 {tf_label} 봉"
    data_desc = (
        f"{symbol} 정규장(09:30~) · {source} · "
        f"A/D 체결 압력(고저-종가 가중) 기반 정밀 CVD"
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
                    iv = num(o.get("volatility"))
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
    if not token:
        return None, {"reason": "토큰 없음"}

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
    single_day_had_today = today_str in exps
    widened = False
    if not single_day_had_today:
        widened = True
        wide = ask(today_date, today_date + timedelta(days=7), 30)
        wide_exps = _chain_exps(wide)
        if wide_exps:
            data, exps = wide, wide_exps
    diag = {
        "requested_date": today_str,
        "single_day_query_had_today": single_day_had_today,
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


def analyze_gex(contracts, spot, scale, exp_date, now_et, source, diag=None):
    S = spot / scale
    y, m, d = (int(x) for x in exp_date.split("-"))
    exp_dt = ET.localize(datetime(y, m, d, 16, 0))
    secs = (exp_dt - now_et).total_seconds()
    T = max(secs, 300.0) / SECONDS_PER_YEAR

    use = [c for c in contracts if 0.9 * S <= c["K"] <= 1.1 * S and c["oi"] > 0]
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
    gamma_source_note = (
        f"감마 {gamma_from_schwab}개는 Schwab 제공값, {gamma_from_calc}개는 자체 계산(Black-Scholes)값"
        if (gamma_from_schwab or gamma_from_calc) else None
    )

    above = [k for k, e in per.items() if k >= S and e["call_oi"] > 0] or [k for k, e in per.items() if e["call_oi"] > 0]
    below = [k for k, e in per.items() if k <= S and e["put_oi"] > 0] or [k for k, e in per.items() if e["put_oi"] > 0]
    call_wall = max(above, key=lambda k: per[k]["call_oi"]) * scale if above else None
    put_wall = max(below, key=lambda k: per[k]["put_oi"]) * scale if below else None

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
            res = analyze_gex(r[0], spx_p, 1.0, r[1], now_et, f"{SRC_SCHWAB} 옵션체인 (SPX/SPXW 단일 만기 {r[1]})", diag)
            if res:
                return res
        if ratio:
            ry = fetch_yahoo_chain(start)
            if ry:
                res = analyze_gex(
                    ry[0], spx_p, ratio, ry[1], now_et,
                    f"{SRC_YAHOO} SPY 옵션체인 (단일 만기 {ry[1]}) x SPX/SPY {ratio:.3f} 환산 · 근사치",
                    diag,
                )
                if res:
                    return res
        return gex_na("옵션체인을 가져오지 못했습니다 (Schwab · Yahoo 모두 실패)", diag)

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
    closes = [c["c"] for c in candles]
    if len(closes) < 22:
        return None
    e9, e21 = ema_series(closes, 9), ema_series(closes, 21)
    comps = [
        sgn(closes[-1] - e9[-1]),
        sgn(e9[-1] - e21[-1]),
    ]
    if len(closes) >= 50:
        e50 = ema_series(closes, 50)
        comps.append(sgn(e21[-1] - e50[-1]))
    else:
        comps.append(0)
    comps.append(sgn(e21[-1] - e21[-4]))
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
# API
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
    with ThreadPoolExecutor(max_workers=10) as ex:
        f_spx = {k: ex.submit(get_candles, token, "spx", k) for k in {"1h", "15m", "5m", "1m", r_key}}
        f_spy_v = ex.submit(get_candles, token, "spy", v_key)
        f_spy_c = ex.submit(get_candles, token, "spy", c_key)
        f_es_5 = ex.submit(get_candles, token, "es", "5m")
        f_gex = ex.submit(get_gex, token, spx_p, ratio_q, now_et)
        f_news = ex.submit(get_news, now_et)
        f_econ = ex.submit(get_today_econ_events, now_et)

    def result(name, fut):
        return guard(name, fut.result)

    spx_c = {k: result(f"candles spx {k}", f) for k, f in f_spx.items()}
    spy_v = result("candles spy vwap", f_spy_v)
    spy_c = result("candles spy cvd", f_spy_c)
    es_5 = result("candles es 5m", f_es_5)
    gex = result("gex", f_gex) or gex_na("GEX 계산 오류")
    news = result("news", f_news)
    econ_events = result("econ_events", f_econ) or {"items": [], "source": "N/A", "error": "계산 오류"}

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
    cvd = guard("cvd", compute_cvd, spy_c["candles"], c_key, spy_c["source"], "SPY") if spy_c else None

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
        "spx": q_spx,
        "es": quotes.get("es"),
        "vix": slim(quotes.get("vix")),
        "vix9d": slim(quotes.get("vix9d")),
        "mag7": quotes.get("mag7"),
        "news": news,
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
            kv_note = "<p style='color:#f59e0b;'>⚠️ 저장소(KV) 저장에 실패했습니다. 아래 값을 환경변수에 직접 넣어주세요.</p>"

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
        <p style="margin-top:16px;color:#f59e0b;">⚠️ 이 페이지의 값은 계정 접근 권한이 담긴 민감한 정보입니다. 캡처해서 공유하지 마세요.</p>
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
