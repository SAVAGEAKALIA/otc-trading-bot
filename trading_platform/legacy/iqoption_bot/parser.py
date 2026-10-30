"""
Signal parsing from Telegram messages.
Extracts asset, direction, duration, and entry time from trade signals.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from .models import TradeSignal
from .config import DEFAULT_TIMEZONE


class SignalParser:
    """Handles parsing of trading signals from Telegram messages."""

    def __init__(self, default_duration: int = 2, timezone: str = DEFAULT_TIMEZONE):
        self.default_duration = default_duration
        try:
            self.timezone = ZoneInfo(timezone)
        except Exception:
            print(f"⚠️ Invalid timezone '{timezone}', using UTC")
            self.timezone = ZoneInfo("UTC")

    def parse(self, message_text: str, available_assets: dict) -> Optional[TradeSignal]:
        """
        Parse raw text into TradeSignal.

        Args:
            message_text: Raw message text
            available_assets: Dict of available assets from IQ Option

        Returns:
            TradeSignal or None if parsing fails
        """
        # Remove emoji flags and other unicode characters that might interfere
        clean_text = re.sub(r'[^\x00-\x7F]+', ' ', message_text)
        text = clean_text.upper()

        # Also keep original for direction detection (emojis matter there)
        original_upper = message_text.upper()

        # Extract asset - look for currency pair pattern
        full_asset_match = re.search(r'\b([A-Z]{3})\s*[/\-\s]\s*([A-Z]{3})\b', text)
        if not full_asset_match:
            return None

        raw_asset = full_asset_match.group(1) + full_asset_match.group(2)

        # Try different asset name formats
        otc_formats = [
            f"{raw_asset}-OTC",
            f"{raw_asset}_OTC",
            f"{raw_asset}OTC",
        ]
        # NOTE: We do NOT use regular_formats - this bot ONLY trades OTC
        # regular_formats = [raw_asset]  # REMOVED - never trade regular pairs

        final_asset = None

        def find_asset_in_dict(asset_dict: dict, formats: list) -> Optional[str]:
            for fmt in formats:
                if fmt in asset_dict and asset_dict[fmt].get('open'):
                    return fmt
                for key in asset_dict:
                    if key.upper().replace("_", "-").replace("OTC", "-OTC") == fmt.upper().replace("_", "-"):
                        if asset_dict[key].get('open'):
                            return key
            return None

        # Check binary options first - ONLY look for OTC formats
        if available_assets and 'binary' in available_assets:
            final_asset = find_asset_in_dict(available_assets['binary'], otc_formats)
            # DO NOT fall back to regular pairs

        # Check turbo options as fallback - ONLY look for OTC formats
        if not final_asset and available_assets and 'turbo' in available_assets:
            final_asset = find_asset_in_dict(available_assets['turbo'], otc_formats)
            # DO NOT fall back to regular pairs

        # ALWAYS use OTC format - this bot ONLY trades OTC markets
        if not final_asset:
            final_asset = otc_formats[0]  # e.g., EURCAD-OTC
            print(f"   📌 OTC Mode: Using {final_asset}")

        # Double-check: ensure final_asset is OTC format
        if final_asset and 'OTC' not in final_asset.upper() and '-op' not in final_asset.lower():
            # Convert to OTC format
            base = final_asset.upper().replace("-OTC", "").replace("-OP", "").replace("_OTC", "")
            final_asset = f"{base}-OTC"
            print(f"   🔄 Forced OTC: {final_asset}")

        # Extract direction
        direction = None
        check_text = original_upper + " " + text

        # Check explicit text patterns first
        text_put_patterns = ["DIRECTION: SELL", "DIRECTION:SELL", "DIRECTION SELL", ": SELL", " SELL ", "SELL ", " PUT ", "PUT "]
        text_call_patterns = ["DIRECTION: BUY", "DIRECTION:BUY", "DIRECTION BUY", ": BUY", " BUY ", "BUY ", " CALL ", "CALL "]

        for pattern in text_put_patterns:
            if pattern in check_text:
                direction = "put"
                break

        if not direction:
            for pattern in text_call_patterns:
                if pattern in check_text:
                    direction = "call"
                    break

        # Use emoji patterns if no explicit text
        if not direction:
            call_emoji_patterns = ["⬆", "🟢", "🔼", "🟩"]
            put_emoji_patterns = ["⬇", "🔴", "🔽", "🟥"]

            if any(x in check_text for x in call_emoji_patterns):
                direction = "call"
            elif any(x in check_text for x in put_emoji_patterns):
                direction = "put"

        # Fallback to generic patterns
        if not direction:
            if any(x in check_text for x in ["UP", "LONG", "GREEN"]):
                direction = "call"
            elif any(x in check_text for x in ["DOWN", "SHORT", "RED"]):
                direction = "put"

        if not direction:
            return None

        # Extract duration
        duration = self.default_duration

        time_patterns = [
            r'(\d+)\s*(?:M(?:IN(?:UTES?)?)?)\b',
            r'\b(?:M)\s*(\d+)\b',
            r'(\d+)\s*(?:MINUTE)',
            r'EXP(?:IRY)?[:\s]*(\d+)',
        ]

        for pattern in time_patterns:
            time_match = re.search(pattern, text)
            if time_match:
                duration = int(time_match.group(1))
                break

        # Validate duration (1-5 minutes for binary)
        duration = max(1, min(duration, 5))

        # Extract entry time
        entry_time = self._parse_entry_time(text)

        return TradeSignal(
            asset=final_asset,
            direction=direction,
            duration=duration,
            entry_time=entry_time
        )

    def _parse_entry_time(self, text: str) -> Optional[datetime]:
        """
        Parse entry time from signal text.

        Supports formats:
        - "Entry Time: 4:02 PM"
        - "Entry Time: 16:02"
        """
        # Pattern for 12-hour format
        pattern_12h = r'ENTRY\s*(?:TIME)?[:\s]*(\d{1,2}):(\d{2})\s*(AM|PM)'
        match = re.search(pattern_12h, text, re.IGNORECASE)

        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            period = match.group(3).upper()

            if period == "PM" and hour != 12:
                hour += 12
            elif period == "AM" and hour == 12:
                hour = 0

            now = datetime.now(self.timezone)
            entry_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            time_diff = (now - entry_time).total_seconds()
            if time_diff > 12 * 3600:
                entry_time = entry_time + timedelta(days=1)

            return entry_time

        # Pattern for 24-hour format
        pattern_24h = r'ENTRY\s*(?:TIME)?[:\s]*(\d{1,2}):(\d{2})(?!\s*[AP]M)'
        match = re.search(pattern_24h, text, re.IGNORECASE)

        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))

            now = datetime.now(self.timezone)
            entry_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            time_diff = (now - entry_time).total_seconds()
            if time_diff > 12 * 3600:
                entry_time = entry_time + timedelta(days=1)

            return entry_time

        return None

