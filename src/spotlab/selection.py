from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any


def ranked_entries(rows: Mapping[str, Any]) -> list[str]:
    """Identical deterministic priority for backtest and paper: score, then symbol."""
    candidates = []
    for symbol, row in rows.items():
        score = float(row.get("signal_score", row.get("confirmation_count", 0) * 25))
        if (
            bool(row.get("enter_long", False))
            and not bool(row.get("exit_long", False))
            and isfinite(score)
        ):
            candidates.append((symbol, score))
    return [symbol for symbol, _ in sorted(candidates, key=lambda item: (-item[1], item[0]))]
