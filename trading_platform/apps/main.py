#!/usr/bin/env python3
"""
OTC Trading Bot - Main Entry Point

Usage:
    python -m trading_platform.apps.main                      # Use config from environment variables
    python -m trading_platform.apps.main --config config.json # Use config from JSON file (optional)

For Docker deployment:
    docker compose up -d

Environment Variables:
    See .env.example for all available options.
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path


# Suppress known iqoptionapi library errors (digital options thread issues)
# These don't affect binary options trading
logging.basicConfig(level=logging.WARNING)
logging.getLogger('iqoptionapi').setLevel(logging.CRITICAL)
logging.getLogger('root').setLevel(logging.WARNING)

# Suppress threading errors from trading_platform.vendor.iqoptionapi.iqoptionapi
import threading
original_excepthook = threading.excepthook

def custom_excepthook(args):
    # Suppress known iqoptionapi errors
    error_str = str(args.exc_value)
    if any(x in error_str for x in ['underlying', 'digital', 'NoneType', 'subscriptable']):
        return  # Silently ignore these known errors
    original_excepthook(args)

threading.excepthook = custom_excepthook

from trading_platform.legacy.iqoption_bot import OTCTradingBot, load_config_from_env
from dotenv import load_dotenv

load_dotenv()

def load_config_from_file(filepath: str) -> dict:
    """Load configuration from a JSON file."""
    with open(filepath, 'r') as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description="OTC Trading Bot for IQ Option",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m trading_platform.apps.main                          # Load config from environment
    python -m trading_platform.apps.main --config my_config.json  # Load config from file
    python -m trading_platform.apps.main --env-only               # Strictly use environment variables

For Docker deployment, set environment variables in .env file.
        """
    )
    parser.add_argument(
        '--config', '-c',
        type=str,
        help='Path to JSON configuration file'
    )
    parser.add_argument(
        '--env-only',
        action='store_true',
        help='Only use environment variables (ignore any config file)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Start in dry-run mode (no real trades)'
    )

    args = parser.parse_args()

    # Load configuration
    if args.config and not args.env_only:
        print(f"📁 Loading config from: {args.config}")
        config = load_config_from_file(args.config)
    elif os.environ.get('TG_API_ID') or os.environ.get('IQ_EMAIL'):
        print("🌍 Loading config from environment variables")
        config = load_config_from_env()
    else:
        print("⚠️  No configuration found!")
        print("    Set environment variables or provide --config file")
        print("    See .env.example for available options")
        sys.exit(1)

    # Override with command-line flags
    if args.dry_run:
        config['dry_run'] = True
        print("🧪 Dry-run mode enabled via command line")

    # Validate essential config
    if not config.get('api_id') or not config.get('api_hash'):
        print("❌ Missing Telegram API credentials!")
        print("   Set TG_API_ID and TG_API_HASH environment variables")
        sys.exit(1)

    if not config.get('iq_email') or not config.get('iq_password'):
        print("❌ Missing IQ Option credentials!")
        print("   Set IQ_EMAIL and IQ_PASSWORD environment variables")
        sys.exit(1)

    if not config.get('channel_name'):
        print("❌ Missing signal channel ID!")
        print("   Set TG_CHANNEL_ID environment variable")
        sys.exit(1)

    # Start bot
    bot = OTCTradingBot(config)
    bot.start()


if __name__ == "__main__":
    main()

