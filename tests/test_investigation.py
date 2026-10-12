"""Investigative views must preserve source counts, exact address scopes and matter privacy."""

from email import policy
from email.parser import BytesParser

from casequarry.ingestion import index_participants
from casequarry.models import Evidence, Participant, Person
from sqlalchemy import func, select

from .evidence_fixtures import eml_bytes
from .test_api_acceptance import app as app
from .test_api_acceptance import create_case, create_reviewer, import_files, search
from .test_api_acceptance import owner as owner


def upload(owner, case_id, raw, name="synthetic.eml"):
    result = import_files(owner, case_id, [("files", (name, raw, "message/rfc822"))])
    assert result["state"] == "completed", result


def test_directory_and_network_distinguish_occurrences_originals_and_recipient_roles(owner, app):
    case_id = create_case(owner)
    message = BytesParser(policy=policy.default).parsebytes(eml_bytes(sender="ALICE@example.test"))
    message["Cc"] = "bob@example.test, carol@example.test"
    message["Bcc"] = "mike@example.test"
    message["Reply-To"] = "help@example.test"
    raw = message.as_bytes(policy=policy.SMTP)
    upload(owner, case_id, raw, "source-one.eml")
    upload(owner, case_id, raw, "source-two.eml")
    response = owner.get(f"/cases/{case_id}/people")
    assert response.status_code == 200, response.text
    directory = {item["email"]: item for item in response.json()["items"]}
    assert set(directory) == {
        "alice@example.test",
        "bob@example.test",
        "carol@example.test",
        "mike@example.test",
        "help@example.test",
    }
    assert directory["alice@example.test"]["sent_count"] == 2
    assert directory["bob@example.test"]["received_count"] == 2
    assert directory["bob@example.test"]["total_count"] == 2
    assert directory["bob@example.test"]["unique_messages"] == 1
    assert directory["help@example.test"]["received_count"] == 0
    network = owner.get(f"/cases/{case_id}/network")
    assert network.status_code == 200, network.text
    result = network.json()
    assert len(result["edges"]) == 3
    assert all(edge["count"] == 2 and edge["unique_messages"] == 1 for edge in result["edges"])
    assert {node["email"] for node in result["nodes"]} == {
        "alice@example.test",
        "bob@example.test",
        "carol@example.test",
        "mike@example.test",
    }
    assert "byte-exact" in result["count_basis"]
    with app.state.db.sessions() as db:
        records = db.scalars(select(Evidence).where(Evidence.case_id == case_id)).all()
        for item in records:
            index_participants(db, item, item.email_metadata)
        db.commit()
        assert db.scalar(select(func.count()).select_from(Person).where(Person.case_id == case_id)) == 5
        assert (
            db.scalar(select(func.count()).select_from(Participant).where(Participant.case_id == case_id))
            == 12
        )


def test_person_message_scope_is_exact_and_cursors_cannot_switch_participants(owner):
    case_id = create_case(owner)
    upload(owner, case_id, eml_bytes(1), "first.eml")
    upload(owner, case_id, eml_bytes(2), "second.eml")
    upload(
        owner,
        case_id,
        eml_bytes(3, sender="alice@example.test.invalid", recipient="different@example.test"),
        "suffix.eml",
    )
    people = {item["email"]: item for item in owner.get(f"/cases/{case_id}/people").json()["items"]}
    alice = people["alice@example.test"]["id"]
    other = people["alice@example.test.invalid"]["id"]
    first = owner.get(f"/cases/{case_id}/people/{alice}/messages", params={"page_size": 1})
    assert first.status_code == 200, first.text
    assert first.json()["total_hits"] == 2
    reusable_scope = search(owner, case_id, filters={"person_id": alice})
    assert reusable_scope["total_hits"] == 2
    cursor = first.json()["next_cursor"]
    assert cursor
    second = owner.get(f"/cases/{case_id}/people/{alice}/messages", params={"page_size": 1, "cursor": cursor})
    assert second.status_code == 200, second.text
    assert first.json()["items"][0]["evidence_id"] != second.json()["items"][0]["evidence_id"]
    wrong_person = owner.get(
        f"/cases/{case_id}/people/{other}/messages", params={"page_size": 1, "cursor": cursor}
    )
    assert wrong_person.status_code == 422
    assert wrong_person.json()["error_code"] == "CURSOR_SCOPE_MISMATCH"
    ordinary = owner.post(f"/cases/{case_id}/search", json={"page_size": 1, "cursor": cursor})
    assert ordinary.status_code == 422


def test_timeline_is_paginated_snapshot_with_missing_dates_explicit(owner):
    case_id = create_case(owner)
    import_files(
        owner,
        case_id,
        [
            ("files", ("first.eml", eml_bytes(1), "message/rfc822")),
            ("files", ("reply.eml", eml_bytes(2), "message/rfc822")),
            ("files", ("tied-date.eml", eml_bytes(29), "message/rfc822")),
            ("files", ("undated.txt", b"Synthetic undated source", "text/plain")),
        ],
    )
    response = owner.get(f"/cases/{case_id}/timeline", params={"limit": 1})
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["total_items"] == 3
    assert first["missing_date_count"] == 1
    assert first["items"][0]["source"] == "metadata"
    assert first["items"][0]["date_utc"].endswith("+00:00")
    upload(owner, case_id, eml_bytes(4), "arrived-after-snapshot.eml")
    ids, cursor = [first["items"][0]["evidence_id"]], first["next_cursor"]
    while cursor:
        response = owner.get(f"/cases/{case_id}/timeline", params={"limit": 1, "cursor": cursor})
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total_items"] == 3
        ids.extend(item["evidence_id"] for item in page["items"])
        cursor = page["next_cursor"]
    assert len(ids) == len(set(ids)) == 3
    assert owner.get(f"/cases/{case_id}/timeline").json()["total_items"] == 4
    other_case = create_case(owner, "OTHER")
    replay = owner.get(f"/cases/{other_case}/timeline", params={"cursor": first["next_cursor"]})
    assert replay.status_code == 422


def test_threads_and_traffic_use_collected_header_links_without_inference(owner):
    case_id = create_case(owner)
    upload(owner, case_id, eml_bytes(1), "first.eml")
    upload(owner, case_id, eml_bytes(2), "reply.eml")
    items = search(owner, case_id)["items"]
    thread_id = items[0]["thread_id"]
    assert thread_id == items[1]["thread_id"]
    result = owner.get(f"/cases/{case_id}/threads/{thread_id}")
    assert result.status_code == 200, result.text
    assert result.json()["total_hits"] == 2
    assert result.json()["inferred_links"] is False
    assert result.json()["completeness"] == "not_assessed"
    email_thread = owner.get(f"/cases/{case_id}/emails/{items[0]['id']}/thread")
    assert email_thread.status_code == 200
    assert email_thread.json()["total_hits"] == 2
    traffic = owner.get(f"/cases/{case_id}/analytics/traffic")
    assert traffic.status_code == 200, traffic.text
    assert sum(bucket["count"] for bucket in traffic.json()["items"]) == 2
    assert traffic.json()["timezone"] == "UTC"
    assert (
        owner.get(f"/cases/{case_id}/analytics/traffic", params={"group_by": "unsupported"}).status_code
        == 422
    )


def test_all_investigation_views_deny_cross_case_ids_and_counts(owner, app):
    visible = create_case(owner, "VISIBLE")
    private = create_case(owner, "PRIVATE")
    upload(owner, private, eml_bytes())
    person_id = owner.get(f"/cases/{private}/people").json()["items"][0]["id"]
    evidence = search(owner, private)["items"][0]
    user_id, reviewer = create_reviewer(owner, app)
    response = owner.post(f"/cases/{visible}/members", json={"user_id": user_id, "role": "reviewer"})
    assert response.status_code == 201
    for endpoint in (
        "people",
        "network",
        "timeline",
        "analytics/traffic",
        "analytics/participants",
        "analytics/communication-network",
        "emails",
        f"people/{person_id}",
        f"people/{person_id}/messages",
        f"emails/{evidence['id']}/thread",
        f"threads/{evidence['thread_id']}",
    ):
        response = reviewer.get(f"/cases/{private}/{endpoint}")
        assert response.status_code == 404, (endpoint, response.text)
    assert reviewer.get(f"/cases/{visible}/people/{person_id}").status_code == 404
    assert (
        reviewer.post(f"/cases/{visible}/people/{person_id}/messages", json={"query": ""}).status_code == 404
    )
