"""
AI-powered trade analysis using OpenAI API.
"""

import re
import json
import asyncio
from typing import Tuple

try:
    import requests
except ImportError:
    requests = None


class AIAnalyzer:
    """Handles AI-based trade analysis using OpenAI API."""

    def __init__(self, api_key: str, enabled: bool = True, confidence_threshold: float = 0.7):
        self.api_key = api_key
        self.enabled = enabled
        self.confidence_threshold = confidence_threshold

    async def analyze(self, asset: str, direction: str, indicators: dict) -> Tuple[bool, float, str]:
        """
        Send market data to AI for trade decision (async).

        Returns:
            Tuple of (should_trade, confidence, reasoning)
        """
        if not self.enabled or not self.api_key or self.api_key == "your_openai_api_key":
            return True, 1.0, "AI disabled - executing signal directly"

        if requests is None:
            return True, 0.5, "requests library not available"

        prompt = f"""
        You are a professional binary options trading analyst. Analyze this trade signal and market data.
        Be conservative - only recommend trades with clear technical confirmation.

        SIGNAL: {asset} - {direction.upper()}

        MARKET DATA:
        - Current Price: {indicators.get('current_price')}
        - RSI (14): {indicators.get('rsi')} (>70 overbought, <30 oversold)
        - SMA 10: {indicators.get('sma_10')}
        - SMA 20: {indicators.get('sma_20')}
        - Trend: {indicators.get('trend')}
        - Momentum: {indicators.get('momentum')}%
        - Volatility: {indicators.get('volatility')}%

        RULES:
        - For CALL: RSI should not be >75, trend should not be strongly bearish
        - For PUT: RSI should not be <25, trend should not be strongly bullish
        - High volatility (>2%) increases risk

        Respond ONLY in this exact JSON format:
        {{"should_trade": true, "confidence": 0.75, "reasoning": "brief explanation"}}
        """

        try:
            # Run in executor to not block async loop
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": 150
                    },
                    timeout=15
                )
            )

            result = response.json()

            if 'error' in result:
                print(f"⚠️ AI API Error: {result['error']}")
                return True, 0.5, "AI API error - proceeding with caution"

            content = result['choices'][0]['message']['content']

            # Clean and parse JSON
            content = content.strip()
            if content.startswith('```'):
                content = re.sub(r'^```json?\s*', '', content)
                content = re.sub(r'\s*```$', '', content)

            analysis = json.loads(content)
            return analysis['should_trade'], analysis['confidence'], analysis['reasoning']

        except json.JSONDecodeError as e:
            print(f"⚠️ AI JSON Parse Error: {e}")
            return True, 0.5, "AI response parse error - proceeding with caution"
        except Exception as e:
            print(f"⚠️ AI Error: {e}")
            return True, 0.5, "AI unavailable - proceeding with caution"

