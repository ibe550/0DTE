import numpy as np
import pandas as pd
from datetime import time as dtime

class SimonsBenterQuantEngine:
    """
    Jim Simons & Bill Benter 스타일의 통계적 퀀트 보조 엔진 (장외 실적/뉴스 대응 강화 버전)
    """

    @staticmethod
    def calculate_zscore_anomaly(price_series, window=20):
        """
        Z-Score 기반 통계적 이상치 감지
        """
        if len(price_series) < window:
            return 0.0
        
        sma = price_series.rolling(window=window).mean().iloc[-1]
        std = price_series.rolling(window=window).std().iloc[-1]
        
        if std == 0 or np.isnan(std):
            return 0.0
            
        current_price = price_series.iloc[-1]
        z_score = (current_price - sma) / std
        return round(z_score, 2)

    @staticmethod
    def get_session_risk_message(session_name):
        """
        세션 이름에 맞는 사용자 경고 메시지(레벨 + 문구)를 반환한다.
        detect_trading_session()이 리턴한 session_name을 그대로 넣으면 된다.
        반환: (risk_level, title, message)
        """
        messages = {
            "OPEN_VOLATILITY": (
                "HIGH", "개장 변동성",
                "개장 직후입니다 — 밤사이 주문이 몰려 변동성이 크고 스프레드도 벌어질 수 있어요. "
                "진입은 신중하게 하세요."
            ),
            "MORNING_TREND": (
                "LOW", "오전 추세 형성",
                "방향성이 잡히는 구간입니다. 비교적 안정적이지만 추세 전환에 유의하세요."
            ),
            "LUNCH_LULL": (
                "MEDIUM", "점심 눌림",
                "점심시간 — 유동성 저하와 가짜 돌파에 주의하세요."
            ),
            "AFTERNOON_TREND": (
                "LOW", "오후 재개",
                "거래량이 다시 붙기 시작하는 구간입니다."
            ),
            "POWER_HOUR_GAMMA_RISK": (
                "EXTREME", "파워아워 감마 위험",
                "0DTE 만기가 몇 시간 안 남아 감마가 극단적으로 커지는 구간입니다. "
                "작은 가격 변동에도 옵션가치가 크게 흔들릴 수 있어요."
            ),
            "AFTER_HOURS_THIN_LIQUIDITY": (
                "HIGH", "장외 저유동성",
                "정규장 밖입니다 — 유동성이 얇아 슬리피지·스프레드 위험이 커집니다."
            ),
        }
        return messages.get(session_name, ("LOW", "일반", "특이사항 없음."))

    @staticmethod
    def detect_trading_session(now_et):
        """
        [0DTE 세션 리스크] 같은 변동성이라도 시간대에 따라 0DTE 옵션의 감마/세타
        위험은 완전히 다르다. 장이 열려있는 동안에도:
          - 개장 직후(09:30~10:00): 밤사이 갭/오더플로우 정리로 변동성 최고조
          - 오전 추세(10:00~11:30): 방향성이 잡히는 구간, 상대적으로 평이
          - 점심 눌림(11:30~13:30): 거래량/변동성이 뚜렷하게 줄어드는 구간
          - 오후 재개(13:30~15:00): 거래량이 다시 붙기 시작
          - 파워아워(15:00~16:00): 0DTE는 만기가 몇 시간 안 남아 감마가 극단적으로
            커지는 구간 -> 작은 가격 움직임도 옵션가치를 크게 흔든다
          - 장외(그 외): 유동성이 얇아 스프레드/슬리피지 위험이 커진다

        반환: (session_name, session_distance_mult)
        session_distance_mult는 detect_market_regime의 regime_mult와 곱해서
        스트라이크 안전거리에 반영한다.
        """
        t = now_et.time()

        if dtime(9, 30) <= t < dtime(10, 0):
            return "OPEN_VOLATILITY", 1.3
        elif dtime(10, 0) <= t < dtime(11, 30):
            return "MORNING_TREND", 1.0
        elif dtime(11, 30) <= t < dtime(13, 30):
            return "LUNCH_LULL", 0.75
        elif dtime(13, 30) <= t < dtime(15, 0):
            return "AFTERNOON_TREND", 1.0
        elif dtime(15, 0) <= t <= dtime(16, 0):
            return "POWER_HOUR_GAMMA_RISK", 1.5
        else:
            return "AFTER_HOURS_THIN_LIQUIDITY", 1.4

    @staticmethod
    def detect_market_regime(df, vix_value):
        """
        [Regime Switching] 변동성 및 가격 움직임 기반 시장 상태 분류
        """
        high = df['High']
        low = df['Low']
        close = df['Close']
        
        tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
        atr_14 = tr.rolling(14).mean().iloc[-1]
        atr_ratio = atr_14 / close.iloc[-1] * 100

        # 야간/장외 실적 발표로 인한 선물 갭파동 감지
        recent_return = (close.iloc[-1] - close.iloc[-12]) / close.iloc[-12] * 100 if len(close) >= 12 else 0

        if vix_value > 25.0 or atr_ratio > 0.8:
            return "HIGH_VOLATILITY_CRASH", 1.8  # 안전거리 1.8배 확대
        elif abs(recent_return) > 0.7:  # 실적 발표 직후 선물 0.7% 이상 폭등/폭락 발생 시
            return "EARNINGS_SURGE_EVENT", 1.6   # 안전거리 1.6배 확대
        elif vix_value < 13.0 and atr_ratio < 0.3:
            return "LOW_VOLATILITY_COMPRESSION", 0.8
        elif close.iloc[-1] > close.rolling(20).mean().iloc[-1]:
            return "BULLISH_TREND", 1.0
        else:
            return "BEARISH_TREND", 1.0

    @staticmethod
    def calculate_fractional_kelly(win_rate, reward_to_risk_ratio, fraction=0.25):
        """
        켈리 공식을 통한 최적 자산 배분 비중 (%)
        """
        p = win_rate / 100.0
        q = 1.0 - p
        b = reward_to_risk_ratio
        
        if b <= 0:
            return 0.0
            
        full_kelly = (p * b - q) / b
        fractional_kelly = max(0.0, full_kelly * fraction)
        
        return round(fractional_kelly * 100, 1)

    @staticmethod
    def advanced_news_scoring(news_title):
        """
        [Multi-factor Text Analytics] 실적(Earnings) 및 장외 악재/호재 가중치 스코어
        """
        keywords_weights = {
            # 실적 및 호재 (+ 점수)
            "earnings": 2.0, "revenue": 1.5, "beat": 2.5, "surpass": 2.0,
            "soar": 2.0, "rally": 1.5, "guidance": 1.5, "cut": 1.5,
            # 실적 부진 및 악재 (- 점수)
            "missed": -2.5, "plunge": -2.5, "drop": -2.0, "war": -3.0,
            "cpi": -2.0, "inflation": -2.0, "tariff": -2.5, "crash": -3.0
        }
        
        title_lower = news_title.lower()
        score = 0.0
        
        for word, weight in keywords_weights.items():
            if word in title_lower:
                score += weight
                
        return round(score, 1)
