from __future__ import annotations

import pytest

from scripts.lib.media_monitoring import (
    AmbiguousMediaKey,
    compute_media_calculation,
    upsert_media_actual,
)


def test_attainment_and_variance_known_values():
    # Synthetic fixture: a non-integer actual exercises float precision.
    calc = compute_media_calculation(actual_spend=512.34, planned_budget=2000.0)
    assert calc.variance_value == pytest.approx(-1487.66)
    assert calc.attainment_percent == pytest.approx(25.617, abs=1e-6)


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


# --- Money normalization (variance is BRL; attainment is a percentage) ---


def test_money_variance_is_exact_two_decimals_for_classic_float_noise_case():
    # 1069.07 - 2000.0 is -930.9300000000001 in binary float.
    calc = compute_media_calculation(actual_spend=1069.07, planned_budget=2000.0)
    assert calc.variance_value == -930.93
    assert repr(calc.variance_value) == "-930.93"


@pytest.mark.parametrize(
    ("actual", "planned", "expected"),
    [(0.3, 0.1, 0.2), (0.1, 0.3, -0.2), (100.10, 100.0, 0.1), (1.15, 0.0, 1.15), (2000.0, 1999.99, 0.01)],
)
def test_classic_float_cases_never_contaminate_money(actual, planned, expected):
    calc = compute_media_calculation(actual_spend=actual, planned_budget=planned)
    assert repr(calc.variance_value) == repr(expected)


def test_planned_zero_keeps_null_attainment_and_money_variance():
    calc = compute_media_calculation(actual_spend=0.3, planned_budget=0.0)
    assert calc.attainment_percent is None
    assert repr(calc.variance_value) == "0.3"


@pytest.mark.parametrize("bad_actual", [None, -0.01, True, "10"])
def test_missing_or_invalid_actual_is_rejected_not_guessed(bad_actual):
    with pytest.raises(ValueError):
        compute_media_calculation(actual_spend=bad_actual, planned_budget=2000.0)


def test_attainment_keeps_full_precision_not_money_rounding():
    calc = compute_media_calculation(actual_spend=1069.07, planned_budget=2000.0)
    assert calc.attainment_percent == 1069.07 / 2000.0 * 100
    calc = compute_media_calculation(actual_spend=1.0, planned_budget=3.0)
    assert calc.attainment_percent == 1.0 / 3.0 * 100  # not 33.33


def test_upserted_record_with_normalized_money_validates_against_monitoring_schema(repo_root, validate):
    media, status = upsert_media_actual(
        [], month="2026-03", channel="meta_ads", actual_spend=1069.07, evidence_ids=["ev-synth-1"],
        observed_at="2026-04-02T10:00:00Z", planned_budget=2000.0,
    )
    assert status == "created" and media[0]["variance_value"] == -930.93
    monitoring = {
        "schema_version": "1.0.0", "client_id": "acme-demo", "quarter_id": "2026-Q1", "updated_at": "2026-04-02T10:00:00Z",
        "objective_progress": {"status": "unknown", "current_value": None, "target_value": 10, "progress_percent": None,
                               "observed_at": None, "evidence_ids": []},
        "media_monitoring": media, "flags": [],
    }
    assert validate(monitoring, repo_root / "schemas/quarter-monitoring.schema.json") == []
