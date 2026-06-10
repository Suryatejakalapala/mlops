from ade.drift.schema_drift import detect, fingerprint


def test_no_drift():
    schema = {"id": "integer", "name": "string"}
    report = detect("orders", schema, dict(schema))
    assert not report.drifted
    assert fingerprint(schema) == fingerprint({"name": "string", "id": "integer"})


def test_added_column_is_additive():
    report = detect("orders", {"id": "integer"}, {"id": "integer", "email": "string"})
    assert report.drifted
    assert not report.breaking
    assert report.changes[0].change == "added"


def test_removed_column_is_breaking():
    report = detect("orders", {"id": "integer", "email": "string"}, {"id": "integer"})
    assert report.breaking
    assert report.changes[0].change == "removed"


def test_type_change_breaking_and_safe_widening():
    breaking = detect("d", {"amount": "double"}, {"amount": "string"})
    assert breaking.breaking

    widened = detect("d", {"amount": "integer"}, {"amount": "double"})
    assert widened.drifted
    assert not widened.breaking


def test_event_shape():
    report = detect("orders", {"a": "string"}, {})
    event = report.to_event()
    assert event["type"] == "schema_drift"
    assert event["breaking"] is True
    assert event["incident_id"] == "schema-orders"
