import pytest
from app.automation.discovery import (
    SurveyRecord,
    DiscoveryResult,
    is_placeholder_option,
    process_and_deduplicate_options,
)


def test_placeholder_removal():
    raw_options = [
        {"text": "--निवडा--", "value": "0"},
        {"text": "1", "value": "1"},
        {"text": "Select", "value": ""},
        {"text": "10/1", "value": "10/1"},
    ]
    seen = set()
    records = []
    valid_count, dup_count = process_and_deduplicate_options(raw_options, "1", seen, records)

    assert valid_count == 2
    assert dup_count == 0
    assert len(records) == 2
    assert records[0].display_text == "1"
    assert records[1].display_text == "10/1"


def test_deduplication():
    raw_prefix_1 = [
        {"text": "10/1", "value": "VAL_10_1"},
        {"text": "10/2", "value": "VAL_10_2"},
    ]
    raw_prefix_2 = [
        {"text": "10/1", "value": "VAL_10_1"},  # Duplicate
        {"text": "20/1", "value": "VAL_20_1"},
    ]

    seen = set()
    records = []
    v1, d1 = process_and_deduplicate_options(raw_prefix_1, "1", seen, records)
    v2, d2 = process_and_deduplicate_options(raw_prefix_2, "2", seen, records)

    assert v1 == 2 and d1 == 0
    assert v2 == 2 and d2 == 1  # 1 duplicate detected
    assert len(records) == 3
    assert [r.display_text for r in records] == ["10/1", "10/2", "20/1"]


def test_slash_identifiers_preserved():
    raw = [{"text": "115/1/A", "value": "115/1/A"}]
    seen = set()
    records = []
    process_and_deduplicate_options(raw, "1", seen, records)

    assert len(records) == 1
    assert records[0].display_text == "115/1/A"
    assert records[0].option_value == "115/1/A"


def test_latin_suffix_preserved():
    raw = [{"text": "10/1/B", "value": "10/1/B"}]
    seen = set()
    records = []
    process_and_deduplicate_options(raw, "1", seen, records)

    assert len(records) == 1
    assert records[0].display_text == "10/1/B"
    assert records[0].option_value == "10/1/B"


def test_devanagari_suffix_preserved():
    raw = [{"text": "10/1/अ", "value": "10/1/अ"}]
    seen = set()
    records = []
    process_and_deduplicate_options(raw, "1", seen, records)

    assert len(records) == 1
    assert records[0].display_text == "10/1/अ"
    assert records[0].option_value == "10/1/अ"


def test_empty_legitimate_result():
    raw = [{"text": "--निवडा--", "value": "0"}]
    seen = set()
    records = []
    valid_count, dup_count = process_and_deduplicate_options(raw, "9", seen, records)

    assert valid_count == 0
    assert dup_count == 0
    assert len(records) == 0


def test_failed_prefix_handling():
    result = DiscoveryResult()
    result.failed_prefixes.append("7")
    result.warnings.append("Failed prefix '7': Network Timeout")

    assert "7" in result.failed_prefixes
    assert len(result.warnings) == 1
    assert "Network Timeout" in result.warnings[0]


def test_prefix_count_aggregation():
    result = DiscoveryResult()
    result.prefix_counts["1"] = 280
    result.prefix_counts["2"] = 165
    result.prefix_counts["3"] = 176

    assert sum(result.prefix_counts.values()) == 621


def test_completeness_subset_passes():
    parent_set = {"1", "10", "100", "101"}
    child_set = {"10", "100"}
    missing = child_set - parent_set

    assert len(missing) == 0


def test_completeness_subset_failure_generates_warning():
    parent_set = {"1", "10"}
    child_set = {"10", "100", "101"}  # "100" and "101" missing in parent
    missing = child_set - parent_set

    assert len(missing) == 2
    warning_msg = f"POSSIBLE_TRUNCATION: {len(missing)} items missing in parent prefix."
    assert "POSSIBLE_TRUNCATION" in warning_msg


def test_duplicate_exact_options():
    raw = [
        {"text": "5/1", "value": "VAL_5_1"},
        {"text": "5/1", "value": "VAL_5_1"},
        {"text": "5/1", "value": "VAL_5_1"},
    ]
    seen = set()
    records = []
    valid_count, dup_count = process_and_deduplicate_options(raw, "5", seen, records)

    assert valid_count == 3
    assert dup_count == 2
    assert len(records) == 1


def test_display_text_value_unchanged():
    raw = [{"text": " 12/A-1/ब ", "value": " 12/A-1/ब "}]
    seen = set()
    records = []
    process_and_deduplicate_options(raw, "1", seen, records)

    assert records[0].display_text == "12/A-1/ब"
    assert records[0].option_value == "12/A-1/ब"
