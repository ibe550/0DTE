"""
뉴스 리스크 티커 / 피드 모듈.
여러 헤드라인을 가져오고, 키워드 매칭으로 리스크 태그(FED, INFLATION 등)를 뽑는다.
"""

from datetime import datetime, timezone
import yfinance as yf

RISK_TAG_KEYWORDS = {
    "FED": ["fed", "powell", "federal reserve", "fomc", "rate hike", "rate cut"],
    "INFLATION": ["inflation", "cpi", "pce"],
    "JOBS": ["jobs", "payroll", "unemployment", "nfp"],
    "RATES": ["rate", "yield", "treasury"],
    "WAR": ["war", "conflict", "military", "strike"],
    "TARIFF": ["tariff", "trade war", "sanction"],
    "EARNINGS": ["earnings", "guidance", "results"],
    "CHINA": ["china", "beijing"],
}


def _time_ago(published_ts):
    """유닉스 타임스탬프 -> '2h ago' 같은 문자열."""
    try:
        pub = datetime.fromtimestamp(published_ts, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - pub
        hours = int(delta.total_seconds() // 3600)
        if hours < 1:
            minutes = int(delta.total_seconds() // 60)
            return f"{max(minutes, 1)}m ago"
        elif hours < 24:
            return f"{hours}h ago"
        else:
            return f"{hours // 24}d ago"
    except Exception:
        return ""


def fetch_news_list(ticker="ES=F", n=5):
    """
    최근 뉴스 n개를 가져온다.
    반환: [{"title": str, "publisher": str, "link": str, "time_ago": str}, ...]
    실패 시 빈 리스트 반환 (에러로 앱을 죽이지 않음).
    """
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
