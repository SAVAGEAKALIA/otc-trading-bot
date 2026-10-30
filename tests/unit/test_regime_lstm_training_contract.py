"""Static contract checks for the cloud-only PyTorch trainer."""

import ast
from pathlib import Path


SOURCE = Path("trading_platform/scripts/training/train_regime_mtf_lstm_v5.py")
COMPATIBLE_SOURCE = Path("trading_platform/scripts/training/train_trading_model_v3.py")


def parsed_source() -> tuple[ast.Module, str]:
    text = SOURCE.read_text(encoding="utf-8")
    return ast.parse(text, filename=str(SOURCE)), text


def literal_assignments(tree: ast.Module) -> dict[str, object]:
    result = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    result[target.id] = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    pass
    return result


def test_lstm_uses_five_chronological_partitions() -> None:
    tree, _ = parsed_source()
    values = literal_assignments(tree)

    assert values["SPLIT_CODES"] == {
        "train": 0,
        "early_stop": 1,
        "calibration": 2,
        "policy": 3,
        "test": 4,
    }
    assert sum(
        values[name]
        for name in (
            "TRAIN_FRACTION",
            "EARLY_STOP_FRACTION",
            "CALIBRATION_FRACTION",
            "POLICY_FRACTION",
            "TEST_FRACTION",
        )
    ) == 1.0


def test_lstm_emits_strict_provenance_and_uses_policy_for_thresholds() -> None:
    _, text = parsed_source()

    assert 'loaders["policy"]' in text
    assert "policy_probability, policy_targets, policy_assets, policy_times" in text
    assert "build_calibration_manifest(" in text
    assert "require_unchanged_dataset(DATA_FILE, dataset_fingerprint)" in text
    assert "independent_policy_partition=True" in text
    assert "strict_provenance_manifest=True" in text


def test_runtime_compatible_lstm_emits_calibration_identity() -> None:
    text = COMPATIBLE_SOURCE.read_text(encoding="utf-8")

    assert "fingerprint_dataset(DATA_FILE)" in text
    assert "build_calibration_manifest(" in text
    assert '"calibration_id": provenance["calibration_id"]' in text
    assert '"strict_provenance_manifest": True' in text
    assert "require_unchanged_dataset(DATA_FILE, dataset_fingerprint)" in text
