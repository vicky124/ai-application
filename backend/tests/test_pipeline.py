import json

from app.container import get_container
from app.domain import DocumentMeta
from app.rag.pipeline import STEPS
from app.rag.text import clean_text, parse_frontmatter

STEP_IDS = [s for s, _ in STEPS]
DOC = b"# Expenses\n\n## Meals\n\nMeals up to 40 USD per day are reimbursable with a receipt.\n\n## Travel\n\nBook flights at least 14 days ahead.\n"


def meta(doc_id="expense-policy", **kw):
    return DocumentMeta(doc_id=doc_id, title="Expense Policy", **kw)


def run(client, filename="expense.md", data=DOC, m=None):
    return list(get_container().pipeline.run(filename, data, m or meta()))


def test_clean_text_and_frontmatter():
    assert clean_text("a \r\n\r\n\r\n\r\nb\x00 \n") == "a\n\nb"
    fm, body = parse_frontmatter("---\ntitle: X\nversion: 2\n---\nBody")
    assert fm == {"title": "X", "version": "2"} and body == "Body"
    assert parse_frontmatter("--- not a header") == ({}, "--- not a header")


def test_pipeline_emits_every_stage_in_order(client):
    events = run(client)
    assert events[0]["type"] == "plan" and [s["id"] for s in events[0]["steps"]] == STEP_IDS
    done = [e for e in events if e["type"] == "step" and e["status"] == "done"]
    assert [e["id"] for e in done] == STEP_IDS
    assert events[-1] == {"type": "complete", "doc_id": "expense-policy", "chunks": done[3]["details"]["chunks"]}
    for e in done:
        assert "duration_ms" in e and e["details"]
    json.dumps(events)  # every event must be JSON-serializable


def test_pipeline_details_show_vector_creation(client):
    done = {e["id"]: e["details"] for e in run(client) if e["type"] == "step" and e["status"] == "done"}
    assert done["chunk"]["previews"] and done["chunk"]["sections"][0].startswith("Expenses")
    assert done["embed"]["dimensions"] == 384 and len(done["embed"]["first_vector_preview"]) == 8
    assert done["store"]["points_upserted"] == done["chunk"]["chunks"]
    assert done["verify"]["chunks_in_index"] == done["chunk"]["chunks"]
    assert done["verify"]["self_retrieval"]["passed"] is True


def test_reingest_replaces_instead_of_duplicating(client):
    first = {e["id"]: e["details"] for e in run(client) if e["type"] == "step" and e["status"] == "done"}
    second = {e["id"]: e["details"] for e in run(client) if e["type"] == "step" and e["status"] == "done"}
    assert second["store"]["previous_chunks_removed"] == first["chunk"]["chunks"]
    assert second["verify"]["chunks_in_index"] == first["chunk"]["chunks"]


def test_pipeline_stops_at_failing_stage(client):
    events = run(client, filename="notes.xyz")
    assert events[-1]["type"] == "failed"
    errored = [e for e in events if e["type"] == "step" and e["status"] == "error"]
    assert errored and errored[0]["id"] == "receive" and "Unsupported" in errored[0]["error"]
    assert not any(e["type"] == "step" and e["id"] == "parse" for e in events)  # later stages never ran

    empty = run(client, data=b"")
    assert empty[-1]["type"] == "failed" and "empty" in empty[-1]["error"].lower()


def test_inactive_document_skips_self_retrieval(client):
    done = {e["id"]: e["details"] for e in run(client, m=meta("draft-doc", status="draft")) if e["type"] == "step" and e["status"] == "done"}
    assert "skipped" in done["verify"]["self_retrieval"]


def test_ingested_document_is_searchable_by_chat(client, alice):
    run(client, m=meta("expense-search"))
    r = client.post("/api/chat", headers=alice, json={"question": "How much can I claim for meals per day?", "model_id": "extractive"}).json()
    assert any(s["doc_id"] == "expense-search" for s in r["sources"])


def post_ingest(client, headers, content=DOC, filename="expense.md", **form):
    data = {"title": "Expense Policy", "doc_id": "stream-doc", **form}
    return client.post("/api/documents/ingest", headers=headers, data=data, files={"file": (filename, content)})


def test_stream_endpoint_returns_ndjson_events(client, hannah):
    r = post_ingest(client, hannah)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in r.text.splitlines()]
    assert events[0]["type"] == "plan" and events[-1]["type"] == "complete"


def test_stream_endpoint_reports_failure_in_stream(client, hannah):
    events = [json.loads(l) for l in post_ingest(client, hannah, filename="x.exe").text.splitlines()]
    assert events[-1]["type"] == "failed"


def test_ingest_endpoint_validation_and_rbac(client, alice, hannah):
    assert post_ingest(client, alice).status_code == 403
    assert post_ingest(client, hannah, doc_id="Bad ID!").status_code == 400
    assert post_ingest(client, hannah, allowed_roles="wizard").status_code == 400
    assert post_ingest(client, hannah, status="weird").status_code == 400


def test_delete_document_removes_chunks(client, hannah):
    post_ingest(client, hannah, doc_id="to-delete")
    assert client.delete("/api/documents/to-delete", headers=hannah).status_code == 200
    assert "to-delete" not in [d["doc_id"] for d in client.get("/api/documents", headers=hannah).json()]
