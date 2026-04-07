from pathlib import Path

from company.meridian_platform.session_history import append_session_event, load_session_events, update_session_event


def test_append_session_event_persists_live_event(tmp_path: Path) -> None:
    event = append_session_event(
        "telegram:123",
        {
            "history_type": "worker_receipt",
            "status": "completed",
            "agent_id": "agent_atlas",
            "text": "research done",
        },
        loom_root=tmp_path,
    )
    payload = load_session_events("telegram:123", loom_root=tmp_path)
    assert payload["source"] == "meridian_session_events"
    assert payload["live"] is True
    assert payload["events"][0]["event_id"] == event["event_id"]
    assert payload["events"][0]["history_type"] == "worker_receipt"


def test_update_session_event_applies_quarantine_metadata(tmp_path: Path) -> None:
    event = append_session_event(
        "telegram:123",
        {
            "history_type": "worker_receipt",
            "status": "completed",
            "agent_id": "agent_atlas",
            "text": "research done",
        },
        loom_root=tmp_path,
    )
    updated = update_session_event(
        "telegram:123",
        event["event_id"],
        {
            "quarantined": True,
            "source_label": "historical_untrusted_receipt",
            "warnings": ["quarantined"],
        },
        loom_root=tmp_path,
    )
    payload = load_session_events("telegram:123", loom_root=tmp_path)
    assert updated is not None
    assert payload["events"][0]["quarantined"] is True
    assert payload["events"][0]["source_label"] == "historical_untrusted_receipt"
