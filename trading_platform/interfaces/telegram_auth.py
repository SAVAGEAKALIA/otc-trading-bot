"""Role and environment authorization for the Telegram operator console."""

from enum import Enum

from trading_platform.domain.environment import TradingEnvironment


class OperatorRole(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


_READ = frozenset({"status", "stats", "orders", "positions", "balance", "help"})
_OPERATE = frozenset(
    {"pause", "resume", "reconcile", "paper_start", "paper_stop", "cancel_order", "reduce_only"}
)
_FORBIDDEN = frozenset(
    {"config", "promote", "credentials", "live_enable", "set_leverage", "set_risk", "arbitrary_order"}
)


def authorize(role: OperatorRole, environment: TradingEnvironment, action: str) -> None:
    action = action.strip().lower()
    if action in _READ:
        return
    if action in _OPERATE and role in {OperatorRole.OPERATOR, OperatorRole.ADMIN}:
        if environment in {TradingEnvironment.LIVE, TradingEnvironment.MICRO_LIVE} and action == "paper_start":
            raise PermissionError("paper controls cannot target live environments")
        return
    if action in _FORBIDDEN:
        raise PermissionError(f"{action} is never authorized through Telegram")
    raise PermissionError(f"role {role.value} cannot perform {action}")
