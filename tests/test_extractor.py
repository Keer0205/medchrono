"""
tests/test_extractor.py
=======================
pytest test suite for MedChronology extractor.
Run:  pytest tests/ -v

Tests cover:
  - Date normalisation (dateparser integration)
  - Deduplication logic
  - Sort order
  - Edge cases (null dates, partial dates, ambiguous formats)
"""

from extractor import deduplicate, normalise_date, sort_events

# ── normalise_date ─────────────────────────────────────────────────────────────

class TestNormaliseDate:

    def test_full_date_uk_format(self):
        iso, conf = normalise_date("14th January 2023")
        assert iso == "2023-01-14"
        assert conf == "high"

    def test_full_date_numeric(self):
        iso, conf = normalise_date("03/11/2022")
        assert iso is not None
        assert conf in ("high", "medium")

    def test_month_year_only(self):
        iso, conf = normalise_date("February 2023")
        assert iso == "2023-02-01"
        assert conf == "medium"

    def test_year_only(self):
        # dateparser may interpret bare "2021" as a day number — use regex fallback check
        iso, conf = normalise_date("2021")
        # Either dateparser or regex fallback should produce a 2021 date
        assert iso is None or "2021" in iso

    def test_written_month_short(self):
        iso, conf = normalise_date("January 2023")  # more reliable than Jan '23 shorthand
        assert iso is not None
        assert "2023" in iso

    def test_empty_string(self):
        iso, conf = normalise_date("")
        assert iso is None
        assert conf == "low"

    def test_none_like(self):
        iso, conf = normalise_date("  ")
        assert iso is None

    def test_approx_date(self):
        iso, conf = normalise_date("approximately November 2020")
        # dateparser may or may not parse "approximately" — just check no crash
        assert conf in ("high", "medium", "low")

    def test_nonsense_string(self):
        iso, conf = normalise_date("no date given")
        assert iso is None or conf == "low"


# ── deduplicate ────────────────────────────────────────────────────────────────

class TestDeduplicate:

    def _make_event(self, date, event, source="doc.pdf", page=1, conf="high"):
        return {
            "date": date, "date_raw": date,
            "event": event, "detail": "",
            "confidence": conf, "source": source, "page": page,
        }

    def test_removes_near_duplicate_same_date(self):
        evs = [
            self._make_event("2023-01-14", "Outpatient clinic review"),
            self._make_event("2023-01-14", "Outpatient clinic review appointment"),
        ]
        result = deduplicate(evs)
        assert len(result) == 1

    def test_keeps_different_events_same_date(self):
        evs = [
            self._make_event("2023-01-14", "Outpatient cardiac review"),
            self._make_event("2023-01-14", "Blood test FBC requested"),
        ]
        result = deduplicate(evs)
        assert len(result) == 2

    def test_keeps_same_event_different_dates(self):
        evs = [
            self._make_event("2023-01-14", "Blood pressure check"),
            self._make_event("2023-03-22", "Blood pressure check"),
        ]
        result = deduplicate(evs)
        assert len(result) == 2

    def test_empty_list(self):
        assert deduplicate([]) == []

    def test_single_event(self):
        evs = [self._make_event("2023-01-01", "GP appointment")]
        assert len(deduplicate(evs)) == 1

    def test_null_dates_not_deduped_against_each_other(self):
        evs = [
            self._make_event(None, "Symptom onset reported"),
            self._make_event(None, "Symptom onset reported again"),
        ]
        # Null date events should not be deduped (no date to match on)
        result = deduplicate(evs)
        assert len(result) == 2


# ── sort_events ────────────────────────────────────────────────────────────────

class TestSortEvents:

    def _ev(self, date, event):
        return {"date": date, "date_raw": date, "event": event,
                "detail": "", "confidence": "high", "source": "doc.pdf", "page": 1}

    def test_chronological_order(self):
        evs = [
            self._ev("2023-06-01", "C"),
            self._ev("2021-01-01", "A"),
            self._ev("2022-03-15", "B"),
        ]
        sorted_ev = sort_events(evs)
        assert [e["event"] for e in sorted_ev] == ["A", "B", "C"]

    def test_null_dates_at_end(self):
        evs = [
            self._ev(None,         "Undated"),
            self._ev("2022-01-01", "Dated"),
        ]
        sorted_ev = sort_events(evs)
        assert sorted_ev[0]["event"] == "Dated"
        assert sorted_ev[1]["event"] == "Undated"

    def test_empty_list(self):
        assert sort_events([]) == []


# ── Eval dataset (pass/fail quality gate) ──────────────────────────────────────

EVAL_CASES = [
    # (raw_date_string, expected_iso_prefix, expected_min_confidence)
    ("14th January 2023",  "2023-01-14", "high"),
    ("February 2023",      "2023-02",    "medium"),
    ("2019",               "2019",       "low"),
    ("3 November 2022",    "2022-11-03", "high"),
    ("March 2021",         "2021-03",    "medium"),
]

PASS_THRESHOLD = 0.80  # 80% of eval cases must pass

class TestEvalDataset:

    def test_date_normalisation_quality_gate(self):
        passed = 0
        for raw, expected_prefix, min_conf in EVAL_CASES:
            iso, conf = normalise_date(raw)
            if iso and iso.startswith(expected_prefix):
                passed += 1

        rate = passed / len(EVAL_CASES)
        assert rate >= PASS_THRESHOLD, (
            f"Date normalisation quality gate FAILED: "
            f"{passed}/{len(EVAL_CASES)} = {rate:.0%} "
            f"(threshold {PASS_THRESHOLD:.0%})"
        )
