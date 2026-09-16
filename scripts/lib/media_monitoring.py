"""Reference arithmetic/upsert logic for monitor-quarter's
`upsert_media_actual` operation (skills/monitor-quarter/SKILL.md section 6).

Pure functions, no I/O — used by the test suite to pin down the exact
contract (attainment/variance formulas, key uniqueness, conflict/no-op
rules) as executable, versioned code instead of only prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class AmbiguousMediaKey(Exception):
    """More than one media_monitoring record exists for the same
    (month, channel) key. monitor-quarter never picks or sums — this is
    always a conflict."""


@dataclass(frozen=True)
class MediaCalculation:
    planned_budget: Optional[float]
    attainment_percent: Optional[float]
    variance_value: Optional[float]


def compute_media_calculation(actual_spend: float, planned_budget: Optional[float]) -> MediaCalculation:
    """attainment_percent = actual/planned*100 (None when planned is None
    or 0); variance_value = actual - planned (None only when planned is
    None)."""
    if planned_budget is None:
        return MediaCalculation(planned_budget=None, attainment_percent=None, variance_value=None)
    variance = actual_spend - planned_budget
    if planned_budget == 0:
        return MediaCalculation(planned_budget=planned_budget, attainment_percent=None, variance_value=variance)
    attainment = actual_spend / planned_budget * 100
    return MediaCalculation(planned_budget=planned_budget, attainment_percent=attainment, variance_value=variance)


def find_media_records(media_monitoring: list[dict], month: str, channel: str) -> list[dict]:
    return [m for m in media_monitoring if m["month"] == month and m["channel"] == channel]


def upsert_media_actual(
    media_monitoring: list[dict],
    *,
    month: str,
    channel: str,
    actual_spend: float,
    evidence_ids: list[str],
    observed_at: str,
    planned_budget: Optional[float],
    pacing_percent: Optional[float] = None,
) -> tuple[list[dict], str]:
    """Returns (new_media_monitoring, status).

    status is one of: "created", "updated", "no_change". Raises
    AmbiguousMediaKey if more than one existing record matches the key —
    monitor-quarter never chooses or sums in that case.
    """
    existing = find_media_records(media_monitoring, month, channel)
    if len(existing) > 1:
        raise AmbiguousMediaKey(f"{len(existing)} existing records for ({month}, {channel})")

    calc = compute_media_calculation(actual_spend, planned_budget)
    new_record = {
        "month": month,
        "channel": channel,
        "actual_spend": actual_spend,
        "observed_at": observed_at,
        "evidence_ids": list(evidence_ids),
        "planned_budget": calc.planned_budget,
        "attainment_percent": calc.attainment_percent,
        "variance_value": calc.variance_value,
        "pacing_percent": pacing_percent,
    }

    if not existing:
        return media_monitoring + [new_record], "created"

    current = existing[0]
    # Identical content (idempotent replay) -> no_change, original list untouched.
    if (
        current["actual_spend"] == new_record["actual_spend"]
        and current["evidence_ids"] == new_record["evidence_ids"]
        and current["observed_at"] == new_record["observed_at"]
        and current["planned_budget"] == new_record["planned_budget"]
        and current["pacing_percent"] == new_record["pacing_percent"]
    ):
        return media_monitoring, "no_change"

    updated = [new_record if (m["month"] == month and m["channel"] == channel) else m for m in media_monitoring]
    return updated, "updated"
