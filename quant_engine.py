import numpy as np
import pandas as pd

class SimonsBenterQuantEngine:
    """
    Jim Simons & Bill Benter 스타일의 통계적 퀀트 보조 엔진
    """

    @staticmethod
    def calculate_zscore_anomaly(price_series, window=20):
        """
        [Simons 스타일] Z-Score 기반 통계적 이상치 감지
        현재 가격이 20봉 이동평균에서 몇 표준편차 떨어져 있는지 계산
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
        [Regime Switching] 시장 상태 분류기
        VIX 및 ATR 기반으로 현재 시장이 어떤 모드인지 정의
        """
        high = df['High']
        low = df['Low']
        close = df['Close']
        
        # ATR (Average True Range) 계산
        tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
        atr_14 = tr.rolling(14).mean().iloc[-1]
        atr_ratio = atr_14 / close.iloc[-1] * 100

        if vix_value > 25.0 or atr_ratio > 0.8:
            return "HIGH_VOLATILITY_CRASH", 1.5  # 행가가격 안전거리 1.5배 확대
        elif vix_value < 13.0 and atr_ratio < 0.3:
            return "LOW_VOLATILITY_COMPRESSION", 0.8  # 프리미엄 수거 위해 타이트하게 설정
        elif close.iloc[-1] > close.rolling(20).mean().iloc[-1]:
            return "BULLISH_TREND", 1.0
        else:
            return "BEARISH_TREND", 1.0

    @staticmethod
    def calculate_fractional_kelly(win_rate, reward_to_risk_ratio, fraction=0.25):
        """
        [Benter 스타일] 켈리 공식을 통한 최적 자산 배분 비중 (%)
        fraction=0.25 (Quarter Kelly: 파산 위험 극소화 안전 장치)
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
        [Multi-factor Text Analytics] 가중치 적용 뉴스 센티멘트 스코어
        """
        keywords_weights = {
            # 악재 가중치 (- 점수)
            "war": -3.0, "cpi": -2.0, "inflation": -2.0, "hike": -1.5,
            "tariff": -2.5, "plunge": -2.0, "crash": -3.0, "fed": -1.0,
            # 호재 가중치 (+ 점수)
            "cut": 2.0, "easing": 2.0, "rally": 1.5, "soar": 2.0,
            "cooling": 1.5, "surpass": 1.0, "stimulus": 2.5
        }
        
        title_lower = news_title.lower()
        score = 0.0
        
        for word, weight in keywords_weights.items():
            if word in title_lower:
                score += weight
                
        return round(score, 1)
