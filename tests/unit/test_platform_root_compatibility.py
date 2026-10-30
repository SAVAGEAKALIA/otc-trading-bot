"""Guard temporary root entry points during platform-package convergence."""

from trading_platform.scripts import generate_otc_shadow_parity_report as legacy_parity
from trading_platform.scripts import build_ml_feature_dataset as legacy_feature_builder
from trading_platform.scripts.training import register_calibration_provenance as legacy_registration
from trading_platform.scripts.training import training_provenance as legacy_provenance
from trading_platform.ml import context_features as legacy_context
from trading_platform.ml import feature_engineering as legacy_engineering
from trading_platform.apps import otc_parity_report, register_calibration
from trading_platform.apps import build_ml_feature_dataset as feature_builder
from trading_platform.research import context_features
from trading_platform.research import feature_engineering
from trading_platform.research import training_provenance


def test_root_training_provenance_is_only_a_compatibility_export() -> None:
    assert legacy_provenance.build_calibration_manifest is training_provenance.build_calibration_manifest
    assert legacy_provenance.fingerprint_dataset is training_provenance.fingerprint_dataset
    assert legacy_provenance.require_unchanged_dataset is training_provenance.require_unchanged_dataset
    assert legacy_provenance.sha256_file is training_provenance.sha256_file


def test_root_application_entry_points_dispatch_to_platform_apps() -> None:
    assert legacy_registration.load_and_verify is register_calibration.load_and_verify
    assert legacy_registration.parse_artifacts is register_calibration.parse_artifacts
    assert legacy_registration.main is register_calibration.main
    assert legacy_parity.main is otc_parity_report.main
    assert legacy_feature_builder.main is feature_builder.main


def test_legacy_market_context_module_reexports_platform_implementation() -> None:
    assert legacy_context.MarketContextProvider is context_features.MarketContextProvider
    assert legacy_context.ContextPolicy is context_features.ContextPolicy
    assert legacy_context.canonical_asset is context_features.canonical_asset


def test_legacy_feature_engineer_reexports_platform_implementation() -> None:
    assert legacy_engineering.FeatureEngineer is feature_engineering.FeatureEngineer
    assert (
        legacy_engineering.FeatureEngineeringError
        is feature_engineering.FeatureEngineeringError
    )
