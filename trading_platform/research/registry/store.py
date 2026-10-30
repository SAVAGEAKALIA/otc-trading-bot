"""Idempotent storage for research-only trial records."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Iterable

from .models import TrialRecord


class TrialRegistry:
    """Store trial evidence without installing or promoting model artifacts."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._trials: dict[str, TrialRecord] = {}
        if self.path is not None and self.path.exists():
            self._load()

    def register(self, trial: TrialRecord) -> bool:
        if not isinstance(trial, TrialRecord):
            raise TypeError("trial must be a TrialRecord")
        existing = self._trials.get(trial.trial_id)
        if existing is not None:
            if existing == trial:
                return False
            raise ValueError("trial_id already belongs to a different trial")
        updated = {**self._trials, trial.trial_id: trial}
        if self.path is not None:
            self._persist(updated.values())
        self._trials = updated
        return True

    def get(self, trial_id: str) -> TrialRecord | None:
        return self._trials.get(trial_id)

    def list_trials(self) -> tuple[TrialRecord, ...]:
        return tuple(self._trials[key] for key in sorted(self._trials))

    def _load(self) -> None:
        assert self.path is not None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid trial registry: {self.path}") from exc
        if raw.get("schema_version") != "trial_registry_v1":
            raise ValueError("unsupported trial registry schema")
        records = raw.get("trials")
        if not isinstance(records, list):
            raise ValueError("trial registry trials must be a list")
        for raw_record in records:
            trial = TrialRecord.from_record(raw_record)
            existing = self._trials.get(trial.trial_id)
            if existing is not None:
                if existing != trial:
                    raise ValueError("trial_id already belongs to a different trial")
                continue
            self._trials[trial.trial_id] = trial

    def _persist(self, trials: Iterable[TrialRecord]) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema_version": "trial_registry_v1",
            "trials": [trial.to_record() for trial in sorted(trials, key=lambda item: item.trial_id)],
        }
        encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_name = handle.name
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if temporary_name is not None and os.path.exists(temporary_name):
                os.unlink(temporary_name)
