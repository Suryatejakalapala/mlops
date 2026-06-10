from ade.etl.quality import evaluate, split_failing_rows

ROWS = [
    {"id": 1, "email": "a@x.com", "price": 10, "status": "open"},
    {"id": 2, "email": "b@x.com", "price": -5, "status": "open"},
    {"id": 2, "email": "", "price": 20, "status": "weird"},
]


def test_not_null_and_unique():
    report = evaluate(ROWS, [
        {"rule": "not_null", "column": "email"},
        {"rule": "unique", "column": "id"},
    ])
    assert not report.passed
    by_rule = {r.rule["rule"]: r for r in report.results}
    assert by_rule["not_null"].failing_rows == 1
    assert by_rule["unique"].failing_rows == 1


def test_range_pattern_and_allowed_values():
    report = evaluate(ROWS, [
        {"rule": "in_range", "column": "price", "min": 0},
        {"rule": "matches", "column": "email", "pattern": "@x\\.com$"},
        {"rule": "allowed_values", "column": "status", "values": ["open", "closed"]},
    ])
    by_rule = {r.rule["rule"]: r for r in report.results}
    assert by_rule["in_range"].failing_rows == 1
    assert by_rule["matches"].passed  # empty value skipped by matches
    assert by_rule["allowed_values"].failing_rows == 1


def test_row_count_and_unknown_rule():
    report = evaluate(ROWS, [{"rule": "row_count_min", "min": 10}, {"rule": "bogus"}])
    assert not report.passed
    assert "unknown rule" in report.results[1].message


def test_split_failing_rows():
    clean, quarantined = split_failing_rows(ROWS, [
        {"rule": "in_range", "column": "price", "min": 0},
        {"rule": "not_null", "column": "email"},
    ])
    assert len(clean) == 1
    assert len(quarantined) == 2
    assert clean[0]["id"] == 1


def test_passing_report_summary():
    report = evaluate(ROWS, [{"rule": "not_null", "column": "id"}])
    assert report.passed
    assert report.summary()["failed_rules"] == []
