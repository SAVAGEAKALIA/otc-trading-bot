#!/usr/bin/env python3
"""Compatibility entry point for the platform-owned feature-dataset builder."""

from trading_platform.apps.build_ml_feature_dataset import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
