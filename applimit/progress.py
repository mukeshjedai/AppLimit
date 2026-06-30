from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# Each phase owns a slice of [0, 1] overall progress (must sum to 1.0).
PHASE_WEIGHTS: dict[str, tuple[float, float]] = {
    "download": (0.0, 0.08),
    "transcribe": (0.08, 0.24),
    "translate": (0.24, 0.34),
    "tts": (0.34, 0.94),
    "mux": (0.94, 1.0),
}

ProgressEmit = Callable[[str, float, float, str], None]
"""(stage, phase_0_1, overall_0_1, detail)"""


@dataclass
class ProgressTracker:
    """Maps per-phase progress into a single monotonic overall bar."""

    emit: ProgressEmit | None

    def fire(self, stage: str, phase_frac: float, detail: str = "") -> None:
        if not self.emit:
            return
        lo, hi = PHASE_WEIGHTS[stage]
        p = max(0.0, min(1.0, phase_frac))
        overall = lo + (hi - lo) * p
        self.emit(stage, p, overall, detail)
