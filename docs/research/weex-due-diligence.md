# WEEX Due Diligence Report

**Date:** 2026-08-20
**Target Phase:** 13

## 1. Jurisdictional & Account Terms
- WEEX operates as an offshore crypto derivatives exchange.
- KYC requirements vary by region; some jurisdictions may be restricted (e.g., US, Canada).
- The API is available to registered accounts with generated API keys.

## 2. API Capabilities & Constraints
- **REST API:** Standard endpoints for market data, account balance, and order placement.
- **WebSocket:** Streams for public market data (trades, orderbook) and private user data (execution reports, balance updates).
- **Rate Limits:** 
  - Standard REST rate limit: ~50 requests/second per IP.
  - Order placement: ~10 requests/second.
- **Sandbox:** A testnet/sandbox environment is available for paper trading.

## 3. Order Execution & Semantics
- **Idempotency:** Orders can be tagged with a `client_oid` (Client Order ID) to ensure idempotency during network partitions.
- **Position Semantics:** WEEX supports both One-Way Mode and Hedge Mode for futures. The platform currently standardizes on Hedge Mode for risk tracking, meaning longs and shorts are tracked as independent position objects.

## 4. Security & Signing
- Authentication requires API Key, API Secret, and an optional Passphrase.
- Signature generation uses HMAC SHA256 over a concatenated string of timestamp + method + request_path + body.

## 5. Conclusion & Next Steps
WEEX meets the foundational requirements for an integration. The adapter will be implemented strictly according to the 4-plane architecture, placing the broker connector in `trading_platform/brokers/weex/`.
