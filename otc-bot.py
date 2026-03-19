import re
import time
from telethon import TelegramClient, events
from iqoptionapi.stable_api import IQ_Option

# ==========================================
# ⚙️ CONFIGURATION (EDIT THIS SECTION)
# ==========================================

# 1. TELEGRAM CONFIG
# Get these from my.telegram.org
API_ID = 35090640  # Your Integer ID
API_HASH = 'eddb54d5272a6bb0487e260ef0fa5585'  # Your String Hash
CHANNEL_NAME = -1002885860160  # 'me' listens to Saved Messages (Great for testing)

# 2. IQ OPTION CONFIG
IQ_EMAIL = "akaliasaviour@gmail.com"
IQ_PASSWORD = "Daddy123$$"
TRADE_AMOUNT = 1  # Amount in $
ACCOUNT_TYPE = "PRACTICE"  # 'PRACTICE' or 'REAL'

# ==========================================
# 🛠️ CORE FUNCTIONS
# ==========================================

# Connect to IQ Option
print("🔌 Connecting to IQ Option...")
api = IQ_Option(IQ_EMAIL, IQ_PASSWORD)
check, reason = api.connect()

if check:
    print(f"✅ Connected to IQ Option! Balance: {api.get_balance()}")
    api.change_balance(ACCOUNT_TYPE)  # Switch to Practice/Real
else:
    print(f"❌ Connection Failed: {reason}")
    exit()


def parse_signal(message_text):
    """
    Parses raw text into (Asset, Direction, Duration).
    """
    text = message_text.upper()

    # 1. EXTRACT ASSET (e.g., EURUSD)
    # Looks for standard 6-letter pairs like EURUSD or GBPJPY
    asset_match = re.search(r'(EUR|GBP|USD|JPY|AUD|NZD|CAD|CHF){2}', text)
    if not asset_match:
        # Fallback: Look for specific pairs if regex fails
        known_assets = ["EURUSD", "GBPUSD", "USDJPY", "AUDCAD"]
        found = next((x for x in known_assets if x in text), None)
        if not found: return None
        raw_asset = found
    else:
        # Use the regex match (e.g., "EUR" + "USD" is not reliable, grab the whole thing)
        # Better simple regex for pairs:
        full_asset_match = re.search(r'([A-Z]{3}.?[A-Z]{3})', text)
        if full_asset_match:
            raw_asset = full_asset_match.group(1).replace("/", "").replace("-", "")
        else:
            return None

    # Force OTC format
    final_asset = f"{raw_asset}-OTC"

    # 2. EXTRACT DIRECTION
    if any(x in text for x in ["CALL", "BUY", "UP"]):
        direction = "call"
    elif any(x in text for x in ["PUT", "SELL", "DOWN"]):
        direction = "put"
    else:
        return None

    # 3. EXTRACT DURATION
    # Looks for "5M", "5 MIN", "M5"
    time_match = re.search(r'(\d+)\s*(M|MIN)|(M)\s*(\d+)', text)
    if time_match:
        minutes = int(time_match.group(1) or time_match.group(4))
    else:
        minutes = 5  # Default fallback

    return final_asset, direction, minutes


def execute_trade(asset, direction, duration):
    """
    Places the trade on IQ Option.
    """
    print(f"\n🚀 SIGNAL RECEIVED: {asset} | {direction.upper()} | {duration}M")

    # Simple Logic: Try 'Binary' (Turbo) first.
    # If you want Digital, that requires different function calls.
    # For Core Functionality, we stick to standard Binary options.

    try:
        check, order_id = api.buy(TRADE_AMOUNT, asset, direction, duration)

        if check:
            print(f"✅ Trade Placed Successfully! ID: {order_id}")
        else:
            print(f"❌ Trade Failed. Reason: {order_id}")

    except Exception as e:
        print(f"⚠️ Error: {e}")


# ==========================================
# 🎧 TELEGRAM LISTENER
# ==========================================

client = TelegramClient('otc_session', API_ID, API_HASH)


@client.on(events.NewMessage(chats=CHANNEL_NAME))
async def handler(event):
    message = event.message.message

    # 1. Parse
    data = parse_signal(message)

    # 2. Execute
    if data:
        asset, direction, duration = data
        execute_trade(asset, direction, duration)
    else:
        # Optional: Print ignored messages to debug regex
        # print(f"Ignored: {message}")
        pass


print("🎧 Bot is listening... Press Ctrl+C to stop.")
client.start()
client.run_until_disconnected()