"""
뉴스 리스크 티커 / 피드 모듈.
여러 헤드라인을 가져오고, 키워드 매칭으로 리스크 태그(FED, INFLATION 등)를 뽑는다.

뉴스 소스: Google News RSS(1순위, 실시간에 가까움) -> 야후 파이낸스(폴백).
Google News는 공식 유료 API 없이 RSS 검색 피드로 무료 조회 가능
(https://news.google.com/rss/search?q=...).
"""

import email.utils
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests
import yfinance as yf

RISK_TAG_KEYWORDS = {
    "FED": ["fed", "powell", "warsh", "federal reserve", "fomc", "rate hike", "rate cut"],
    "INFLATION": ["inflation", "cpi", "pce"],
    "JOBS": ["jobs", "payroll", "unemployment", "nfp"],
    "RATES": ["rate", "yield", "treasury"],
    "WAR": ["war", "conflict", "military", "strike"],
    "TARIFF": ["tariff", "trade war", "sanction"],
    "EARNINGS": ["earnings", "guidance", "results"],
    "CHINA": ["china", "beijing"],
}

GOOGLE_NEWS_QUERY = "S&P 500 OR stock market OR Federal Reserve OR inflation"


def _time_ago(published_ts):
    """유닉스 타임스탬프 -> '2h ago' 같은 문자열."""
    try:
        pub = datetime.fromtimestamp(published_ts, tz=timezone.utc)
        return _time_ago_from_dt(pub)
    except Exception:
        return ""


def _time_ago_from_dt(pub_dt):
    now = datetime.now(timezone.utc)
    delta = now - pub_dt
    seconds = delta.total_seconds()
    if seconds < 3600:
        return f"{max(int(seconds // 60), 1)}m ago"
    elif seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    else:
        return f"{int(seconds // 86400)}d ago"


def fetch_google_news(query=GOOGLE_NEWS_QUERY, n=5):
    """
    Google News RSS 검색 피드로 최신 뉴스를 가져온다.
    반환: ([{"title","publisher","link","time_ago"}, ...], error_or_None)
    """
    try:
        resp = requests.get(
            "https://news.google.com/rss/search",
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        resp.raise_for_status()
    except Exception as e:
        return [], f"Google News 요청 실패: {e}"

    try:
        root = ET.fromstring(resp.content)
    except Exception as e:
        return [], f"Google News 응답 파싱 실패: {e}"

    items = root.findall(".//item")
    if not items:
        return [], "Google News 응답에 기사가 없습니다."

    results = []
    for item in items[:n]:
        title_full = (item.findtext("title") or "").strip()
        link = item.findtext("link") or "#"
        pub_date_str = item.findtext("pubDate")
        source_elem = item.find("source")
        source = source_elem.text.strip() if source_elem is not None and source_elem.text else None

        # Google News 제목은 보통 "헤드라인 - 출처" 형식이라, source가 따로 있으면 뒤에 붙은 걸 잘라낸다
        title = title_full
        if source and title_full.endswith(f" - {source}"):
            title = title_full[: -(len(source) + 3)]

        time_ago = ""
        if pub_date_str:
            try:
                dt = email.utils.parsedate_to_datetime(pub_date_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                time_ago = _time_ago_from_dt(dt)
            except Exception:
                time_ago = ""

        if title:
            results.append({
                "title": title,
                "publisher": source or "Google News",
                "link": link,
                "time_ago": time_ago,
            })

    return results, None


def fetch_news_list(ticker="ES=F", n=5):
    """
    최근 뉴스 n개를 가져온다. Google News를 우선 시도하고, 실패하면 야후로 폴백한다.
    반환: [{"title": str, "publisher": str, "link": str, "time_ago": str}, ...]
    """
    google_items, google_err = fetch_google_news(n=n)
    if not google_err and google_items:
        return google_items

    return _fetch_yahoo_news_list(ticker=ticker, n=n)


def _fetch_yahoo_news_list(ticker="ES=F", n=5):
    """야후 파이낸스 뉴스 (Google News 실패 시 폴백)."""
    try:
        t = yf.Ticker(ticker)
        news_list = t.news or []
    except Exception:
        return []

    result = []
    for item in news_list[:n]:
        # yfinance 버전에 따라 content가 중첩 dict인 경우가 있어 방어적으로 처리
        content = item.get("content", item)
        title = content.get("title") or item.get("title", "")
        publisher = (content.get("provider", {}) or {}).get("displayName") \
            if isinstance(content.get("provider"), dict) else item.get("publisher", "")
        link = ""
        if isinstance(content.get("canonicalUrl"), dict):
            link = content["canonicalUrl"].get("url", "")
        link = link or item.get("link", "") or "#"

        pub_ts = item.get("providerPublishTime")
        time_ago = _time_ago(pub_ts) if pub_ts else ""

        if title:
            result.append({
                "title": title,
                "publisher": publisher or "News",
                "link": link,
                "time_ago": time_ago,
            })

    return result


def extract_risk_tags(news_items):
    """
    뉴스 제목들에서 리스크 태그를 키워드 매칭으로 뽑는다.
    반환: ["FED", "INFLATION", ...] (중복 제거, 등장 순서 유지)
    """
    combined_text = " ".join(item.get("title", "") for item in news_items).lower()
    tags = []
    for tag, keywords in RISK_TAG_KEYWORDS.items():
        if any(kw in combined_text for kw in keywords):
            tags.append(tag)
    return tags
