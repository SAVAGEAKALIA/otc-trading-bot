"""Frozen columns and scope shared by canonical OTC matrix producer/consumer."""
ASSETS = ('EURUSD-OTC', 'GBPUSD-OTC')
FEATURES = ('f_return_lookback', 'f_own_mood', 'f_market_mood', 'f_payout',
            'f_quote_age_ms', 'f_mood_age_ms', 'f_payout_age_ms')
COLUMNS = ('opportunity_id', 'asset', 'decision_ms', 'expiry_ms', 'status',
           'label', 'payout', *FEATURES, 'evidence_class')
MANIFEST_SCHEMA = 'otc_price_proxy_training_v1'
