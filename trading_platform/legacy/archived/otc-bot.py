#!/usr/bin/env python3
"""Deprecated compatibility entry point.

Use ``python -m trading_platform.apps.main`` instead.  Keeping this tiny wrapper avoids a second
execution path that can bypass the application's risk, logging, settlement,
and configuration services.
"""

from main import main


if __name__ == "__main__":
    main()
