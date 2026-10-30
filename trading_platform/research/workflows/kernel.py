"""Fail-closed durable workflow primitives with no trading authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import MappingProxyType
from typing import Any


class WorkflowStatus(str, Enum):
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    approval_id: str
    reason: str
    requested_by: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.approval_id, self.reason, self.requested_by)):
            raise ValueError("approval fields must not be empty")


@dataclass(frozen=True, slots=True)
class WorkflowCheckpoint:
    workflow_id: str
    step: str
    status: WorkflowStatus
    state: Mapping[str, Any]
    revision: int
    approval: ApprovalRequest | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.workflow_id.strip() or not self.step.strip():
            raise ValueError("workflow identity must not be empty")
        if self.revision < 0:
            raise ValueError("workflow revision must be non-negative")
        frozen = _freeze(self.state)
        if not isinstance(frozen, Mapping):
            raise ValueError("workflow state must be an object")
        object.__setattr__(self, "state", frozen)

    @property
    def digest(self) -> str:
        raw = json.dumps(_json(self.state), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class InMemoryWorkflowStore:
    def __init__(self) -> None:
        self._items: dict[str, WorkflowCheckpoint] = {}

    def save(self, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
        current = self._items.get(checkpoint.workflow_id)
        if current is not None and checkpoint.revision < current.revision:
            raise ValueError("workflow revision cannot move backwards")
        self._items[checkpoint.workflow_id] = checkpoint
        return checkpoint

    def load(self, workflow_id: str) -> WorkflowCheckpoint:
        try:
            return self._items[workflow_id]
        except KeyError as exc:
            raise KeyError("workflow checkpoint not found") from exc


class JsonWorkflowStore:
    """Atomic local checkpointer for research/incident workflow state only."""

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)

    def save(self, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
        try:
            current = self.load(checkpoint.workflow_id)
        except KeyError:
            current = None
        if current is not None and checkpoint.revision < current.revision:
            raise ValueError("workflow revision cannot move backwards")
        target = self._path(checkpoint.workflow_id)
        record = {
            "workflow_id": checkpoint.workflow_id,
            "step": checkpoint.step,
            "status": checkpoint.status.value,
            "state": _json(checkpoint.state),
            "revision": checkpoint.revision,
            "approval": None if checkpoint.approval is None else {
                "approval_id": checkpoint.approval.approval_id,
                "reason": checkpoint.approval.reason,
                "requested_by": checkpoint.approval.requested_by,
            },
            "error": checkpoint.error,
        }
        fd, temporary = tempfile.mkstemp(dir=self._directory, prefix=".workflow-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return checkpoint

    def load(self, workflow_id: str) -> WorkflowCheckpoint:
        target = self._path(workflow_id)
        try:
            record = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError("workflow checkpoint not found") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("workflow checkpoint is malformed") from exc
        if not isinstance(record, Mapping):
            raise ValueError("workflow checkpoint must be an object")
        approval_record = record.get("approval")
        approval = None
        if approval_record is not None:
            if not isinstance(approval_record, Mapping):
                raise ValueError("workflow approval is malformed")
            approval = ApprovalRequest(
                str(approval_record.get("approval_id", "")),
                str(approval_record.get("reason", "")),
                str(approval_record.get("requested_by", "")),
            )
        try:
            return WorkflowCheckpoint(
                str(record["workflow_id"]), str(record["step"]),
                WorkflowStatus(str(record["status"])), record["state"],
                int(record["revision"]), approval,
                None if record.get("error") is None else str(record["error"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("workflow checkpoint fields are malformed") from exc

    def _path(self, workflow_id: str) -> Path:
        normalized = workflow_id.strip()
        if not normalized or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in normalized):
            raise ValueError("workflow_id is not a portable identifier")
        return self._directory / f"{normalized}.json"


class ReadOnlyToolRegistry:
    """Only explicitly registered functions can be called by a workflow."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, function: Callable[..., Any]) -> None:
        normalized = name.strip()
        if not normalized or normalized in self._tools:
            raise ValueError("tool name is empty or already registered")
        self._tools[normalized] = function

    def call(self, name: str, **parameters: Any) -> Any:
        try:
            function = self._tools[name]
        except KeyError as exc:
            raise PermissionError("workflow tool is not allowlisted") from exc
        return function(**parameters)


class WorkflowEngine:
    def __init__(self, store: InMemoryWorkflowStore | JsonWorkflowStore, tools: ReadOnlyToolRegistry) -> None:
        self._store = store
        self._tools = tools

    def start(self, workflow_id: str, *, state: Mapping[str, Any]) -> WorkflowCheckpoint:
        checkpoint = WorkflowCheckpoint(workflow_id, "start", WorkflowStatus.RUNNING, state, 0)
        return self._store.save(checkpoint)

    def run_step(
        self,
        workflow_id: str,
        *,
        step: str,
        tool: str,
        parameters: Mapping[str, Any],
        require_approval: ApprovalRequest | None = None,
    ) -> WorkflowCheckpoint:
        current = self._store.load(workflow_id)
        if current.status in {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED}:
            return current
        if (
            current.status is WorkflowStatus.RUNNING
            and current.step == step
            and step in current.state
        ):
            return current
        if require_approval is not None:
            return self._store.save(
                WorkflowCheckpoint(
                    workflow_id, step, WorkflowStatus.WAITING_APPROVAL,
                    current.state, current.revision + 1, require_approval,
                )
            )
        result = self._tools.call(tool, **dict(parameters))
        if not isinstance(result, Mapping):
            raise ValueError("workflow tools must return object state")
        state = dict(current.state)
        state[step] = dict(result)
        return self._store.save(
            WorkflowCheckpoint(workflow_id, step, WorkflowStatus.RUNNING, state, current.revision + 1)
        )

    def complete(self, workflow_id: str) -> WorkflowCheckpoint:
        current = self._store.load(workflow_id)
        if current.status is WorkflowStatus.COMPLETED:
            return current
        if current.status is WorkflowStatus.WAITING_APPROVAL:
            raise ValueError("cannot complete a workflow waiting for approval")
        return self._store.save(
            WorkflowCheckpoint(
                workflow_id, current.step, WorkflowStatus.COMPLETED,
                current.state, current.revision + 1,
            )
        )

    def approve(self, workflow_id: str, approval_id: str) -> WorkflowCheckpoint:
        current = self._store.load(workflow_id)
        if current.status is not WorkflowStatus.WAITING_APPROVAL or current.approval is None:
            raise ValueError("workflow is not waiting for approval")
        if approval_id != current.approval.approval_id:
            raise PermissionError("approval identity mismatch")
        return self._store.save(
            WorkflowCheckpoint(
                workflow_id, current.step, WorkflowStatus.RUNNING,
                current.state, current.revision + 1,
            )
        )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise ValueError("workflow state contains a non-serializable value")


def _json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    return value
