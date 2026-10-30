
import asyncio
import unittest
from unittest.mock import MagicMock, patch

class TestBlacklistReset(unittest.IsolatedAsyncioTestCase):
    async def test_blacklist_reset_command(self):
        print("\n🧪 Testing Blacklist Reset Command...")
        
        from trading_platform.legacy.iqoption_bot.commands import CommandHandler
        from trading_platform.legacy.iqoption_bot.scanner import OTCScanner
        
        # Setup Mocks
        mock_bot = MagicMock()
        mock_bot.api_worker = MagicMock()
        mock_scanner = MagicMock(spec=OTCScanner)
        mock_scanner.asset_performance = {"EURUSD-OTC": {"wins": 1, "losses": 5}}
        mock_scanner.config = MagicMock()
        
        mock_bot.api_worker.scanner = mock_scanner
        
        handler = CommandHandler(mock_bot)
        
        # Execute reset command
        print("   -> Sending /scanner blacklist_reset")
        response = await handler.handle(MagicMock(sender_id=123), "scanner", "blacklist_reset")
        
        print(f"   -> Response: {response}")
        
        # Verify
        self.assertEqual(len(mock_scanner.asset_performance), 0, "Asset performance should be cleared")
        self.assertIn("RESET", response)
        print("   ✅ Blacklist reset verified.")

if __name__ == "__main__":
    unittest.main()
