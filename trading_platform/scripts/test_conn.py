import logging
import os

logging.basicConfig(level=logging.DEBUG)


def main():
    email = os.environ.get("IQ_EMAIL", "")
    password = os.environ.get("IQ_PASSWORD", "")
    if not email or not password:
        raise SystemExit("Set IQ_EMAIL and IQ_PASSWORD before running this manual check")

    # Import only when the manual diagnostic is executed.  Importing the API
    # during pytest collection can pre-load a different editable checkout and
    # invalidate the bundled-client regression tests.
    from trading_platform.vendor.iqoptionapi.iqoptionapi.stable_api import IQ_Option

    print("Starting connection test...")
    api = IQ_Option(email, password)
    print("Calling connect()...")
    check, reason = api.connect()
    print(f"Result: {check}, Reason: {reason}")


if __name__ == "__main__":
    main()
