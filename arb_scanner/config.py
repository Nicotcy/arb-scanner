"""Configuration defaults for arb-scanner."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ScannerConfig:
    dry_run: bool
    alert_only: bool
    alert_threshold: float
    fee_buffer_bps: int


def _env_flag(name: str, default: str) -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


def load_config() -> ScannerConfig:
    """Load configuration from environment with safe defaults."""

    dry_run = _env_flag("DRY_RUN", "1")
    alert_only = _env_flag("ALERT_ONLY", "0")
    alert_threshold = float(os.getenv("ALERT_THRESHOLD", "0.02"))
    fee_buffer_bps = int(os.getenv("FEE_BUFFER_BPS", "25"))

    return ScannerConfig(
        dry_run=dry_run,
        alert_only=alert_only,
        alert_threshold=alert_threshold,
        fee_buffer_bps=fee_buffer_bps,
    )
