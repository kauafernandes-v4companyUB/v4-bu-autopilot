from __future__ import annotations

import pytest

from scripts.lib.media_monitoring import (
    AmbiguousMediaKey,
    compute_media_calculation,
    upsert_media_actual,
)


def test_attainment_and_variance_known_values():
    # Pinned against the real Walmaq apply (September 2026, Meta Ads).
    calc = compute_media_calculation(actual_spend=485.88, planned_budget=2000.0)
    assert calc.variance_value == pytest.approx(-1514.12)
    assert calc.attainment_percent == pytest.approx(24.294, abs=1e-6)


def test_planned_zero_gives_null_attainment_but_real_variance():
    calc = compute_media_calculation(actual_spend=50.0, planned_budget=0.0)
    assert calc.attainment_percent is None
    assert calc.variance_value == pytest.approx(50.0)


def test_planned_none_gives_null_attainment_and_null_variance():
    calc = compute_media_calculation(actual_spend=50.0, planned_budget=None)
    assert calc.attainment_percent is None
    assert calc.variance_value is None


def test_upsert_creates_when_no_existing_record():
    media, status = upsert_media_actual(
        [],
        month="2026-01",
        channel="meta_ads",
        actual_spend=400.0,
        evidence_ids=["ev-1"],
        observed_at="2026-01-15T00:00:00Z",
        planned_budget=1000.0,
    )
    assert status == "created"
    assert len(media) == 1
    assert media[0]["attainment_percent"] == pytest.approx(40.0)


def test_upsert_is_idempotent_no_change_on_identical_replay():
    media, status1 = upsert_media_actual(
        [], month="2026-01", channel="meta_ads", actual_spend=400.0,
        evidence_ids=["ev-1"], observed_at="2026-01-15T00:00:00Z", planned_budget=1000.0,
    )
    media2, status2 = upsert_media_actual(
        media, month="2026-01", channel="meta_ads", actual_spend=400.0,
        evidence_ids=["ev-1"], observed_at="2026-01-15T00:00:00Z", planned_budget=1000.0,
    )
    assert status1 == "created"
    assert status2 == "no_change"
    assert media2 == media  # no duplicate, no mutation
    assert len(media2) == 1


def test_upsert_updates_in_place_on_same_key_different_value():
    media, _ = upsert_media_actual(
        [], month="2026-01", channel="meta_ads", actual_spend=400.0,
        evidence_ids=["ev-1"], observed_at="2026-01-15T00:00:00Z", planned_budget=1000.0,
    )
    media2, status = upsert_media_actual(
        media, month="2026-01", channel="meta_ads", actual_spend=700.0,
        evidence_ids=["ev-1", "ev-2"], observed_at="2026-01-20T00:00:00Z", planned_budget=1000.0,
    )
    assert status == "updated"
    assert len(media2) == 1  # still one record for the key, never two
    assert media2[0]["actual_spend"] == 700.0


def test_upsert_never_creates_second_record_for_same_month_channel():
    media, _ = upsert_media_actual(
        [], month="2026-01", channel="meta_ads", actual_spend=400.0,
        evidence_ids=["ev-1"], observed_at="2026-01-15T00:00:00Z", planned_budget=1000.0,
    )
    media, _ = upsert_media_actual(
        media, month="2026-01", channel="meta_ads", actual_spend=900.0,
        evidence_ids=["ev-1"], observed_at="2026-01-31T00:00:00Z", planned_budget=1000.0,
    )
    matches = [m for m in media if m["month"] == "2026-01" and m["channel"] == "meta_ads"]
    assert len(matches) == 1


def test_different_channel_same_month_creates_separate_record():
    media, _ = upsert_media_actual(
        [], month="2026-01", channel="meta_ads", actual_spend=400.0,
        evidence_ids=["ev-1"], observed_at="2026-01-15T00:00:00Z", planned_budget=1000.0,
    )
    media, status = upsert_media_actual(
        media, month="2026-01", channel="google_ads", actual_spend=0.0,
        evidence_ids=["ev-2"], observed_at="2026-01-15T00:00:00Z", planned_budget=0.0,
    )
    assert status == "created"
    assert len(media) == 2  # never conflated across channels


def test_ambiguous_existing_records_raise_instead_of_choosing():
    duplicated = [
        {"month": "2026-01", "channel": "meta_ads", "actual_spend": 1.0, "observed_at": "t", "evidence_ids": [], "planned_budget": 1.0, "attainment_percent": 100.0, "variance_value": 0.0, "pacing_percent": None},
        {"month": "2026-01", "channel": "meta_ads", "actual_spend": 2.0, "observed_at": "t", "evidence_ids": [], "planned_budget": 1.0, "attainment_percent": 200.0, "variance_value": 1.0, "pacing_percent": None},
    ]
    with pytest.raises(AmbiguousMediaKey):
        upsert_media_actual(
            duplicated, month="2026-01", channel="meta_ads", actual_spend=5.0,
            evidence_ids=["ev-1"], observed_at="2026-01-15T00:00:00Z", planned_budget=1.0,
        )
