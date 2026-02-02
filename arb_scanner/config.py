"""Configuration defaults for arb-scanner.

This project is intentionally conservative:
- DRY_RUN stays on.
- Mode changes policy (thresholds + observability), not architecture.

Env vars are optional overrides. CLI --mode should override env MODE.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ScannerConfig:
    # Safety
    dry_run: bool

    # Mode / policy
    mode: str  # "lab" | "safe"

    # Legacy knobs (kept for backwards-compat)
    alert_only: bool  # if True, use alert_threshold as min edge for opportunities
    alert_threshold: float

    # Opportunity filtering
    min_edge_opportunity: float
    min_executable_size: float

    # Near-miss filtering / observability
    near_miss_edge_floor: float
    near_miss_include_weird_sums: bool

    # Costs / friction
    fee_buffer_bps: int


def _env_flag(name: str, default: str) -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _mode_defaults(mode: str) -> dict:
    m = (mode or "lab").strip().lower()
    if m not in {"lab", "safe"}:
        m = "lab"

    if m == "safe":
        # SAFE: higher edge requirement + higher liquidity requirement + no "weird" observability.
        return {
            "mode": "safe",
            "min_edge_opportunity": float(os.getenv("SAFE_MIN_EDGE", "0.015")),
            "min_executable_size": float(os.getenv("SAFE_MIN_EXEC_SIZE", "10")),
            "near_miss_edge_floor": float(os.getenv("SAFE_NEAR_MISS_FLOOR", "-0.005")),
            "near_miss_include_weird_sums": False,
        }

    # LAB: be more permissive + show weird sums for debugging/learning.
    return {
        "mode": "lab",
        "min_edge_opportunity": float(os.getenv("LAB_MIN_EDGE", "0.0")),
        "min_executable_size": float(os.getenv("LAB_MIN_EXEC_SIZE", "1")),
        "near_miss_edge_floor": float(os.getenv("LAB_NEAR_MISS_FLOOR", "-0.05")),
        "near_miss_include_weird_sums": _env_flag("LAB_INCLUDE_WEIRD_SUMS", "1"),
    }


def load_config() -> ScannerConfig:
    """Load configuration from environment with safe defaults."""

    dry_run = _env_flag("DRY_RUN", "1")

    # Mode comes from env by default, but CLI should override it later.
    env_mode = os.getenv("MODE", "lab")
    md = _mode_defaults(env_mode)

    # Legacy alert knobs (still respected).
    alert_only = _env_flag("ALERT_ONLY", "0")
    alert_threshold = float(os.getenv("ALERT_THRESHOLD", "0.02"))

    fee_buffer_bps = int(os.getenv("FEE_BUFFER_BPS", "25"))

    return ScannerConfig(
        dry_run=dry_run,
        mode=md["mode"],
        alert_only=alert_only,
        alert_threshold=alert_threshold,
        min_edge_opportunity=md["min_edge_opportunity"],
        min_executable_size=md["min_executable_size"],
        near_miss_edge_floor=md["near_miss_edge_floor"],
        near_miss_include_weird_sums=md["near_miss_include_weird_sums"],
        fee_buffer_bps=fee_buffer_bps,
    )
