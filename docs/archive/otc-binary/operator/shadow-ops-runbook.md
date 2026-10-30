# Extended Paper/Shadow Operations Runbook

**Phase 14 Validation Requirements**
To exit Phase 14 and proceed to Micro-Live (Phase 15), the system must run continuously in shadow/paper mode for 2 weeks with NO critical reconciliation errors or unhandled system panics.

## 1. Incident Drills
Operators must randomly inject the following faults during the shadow period to verify systemic resilience:
- **Network Partition:** Simulate provider API outage by blackholing DNS for Bybit/IQOption/WEEX endpoints for 15 minutes.
- **WebSocket Disconnect:** Force TCP resets on the market data streams to ensure graceful fallback to REST and clean reconnection logic.
- **Process Crash:** Terminate the `main.py` daemon `SIGKILL -9` and restart. Verify that idempotent order submissions do not double-spend or duplicate positions.

## 2. Backup and Restore Procedures
- **Ledger Backups:** PostgreSQL pg_dump must run every 12 hours.
- **Restore Test:** Weekly, pull a random backup and restore it to a clean database, verifying the checksum of open positions matches the point-in-time expectation.

## 3. Drift Reporting
The `generate_drift_report.py` script must be run daily. It calculates:
- **Slippage Drift:** The delta between shadow execution prices and the theoretical model entry price.
- **Agent Drift:** For Hermes integrated strategies, the consistency of decisions compared to offline benchmark baselines.

## 4. Promotion Gates
- Zero double-spend incidents.
- Zero silent deadlocks (all components must emit heartbeats).
- Reconciliation mismatch must be `$0.00` across all ledgers over the 2-week period.
