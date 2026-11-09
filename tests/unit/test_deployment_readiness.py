from pathlib import Path

from trading_platform.apps.deployment_readiness import audit


def test_repository_passes_offline_readiness_audit():
    assert audit(Path(__file__).parents[2]) == ()
