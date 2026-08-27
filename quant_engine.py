import numpy as np
import pandas as pd

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
