"""
Tests for Phase 1 Tone Profile system (Ben's ask, 2026-08-27). Covers:
- version numbering per (client, context)
- pending status by default, activate/reject transitions
- only-one-active-per-(client,context) constraint
- source_mix accumulation across versions
- input validation (source_type, min length)

call_anthropic is patched everywhere so tests don't hit the real API.

Run: python test_tone_profile.py
"""

import json
import os
import sqlite3
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")


def _fresh_app(db_path):
    if os.path.exists(db_path):
        os.remove(db_path)
    os.environ["DB_PATH"] = db_path
    import importlib
    import db as hemingway_db
    importlib.reload(hemingway_db)
    hemingway_db.DB_PATH = db_path
    import app as hemingway_app
    importlib.reload(hemingway_app)
    hemingway_app.DB_PATH = db_path
    return hemingway_app


def _client(app_module):
    c = app_module.app.test_client()
    with c.session_transaction() as sess:
        sess["logged_in"] = True
    return c


def _seed_client(db_path, name="Test Co"):
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, ?, '')", (name,))
    raw.commit()
    raw.close()


FAKE_PROFILE = {
    "summary": "Warm, direct, plainspoken.",
    "voice_do": ["state claims without hedging", "use concrete numbers"],
    "voice_dont": ["use corporate jargon", "end on a question"],
    "joy": {"score": 40, "confidence": 60, "note": "Occasional warmth.", "supporting_quote": "That was fun."},
    "confidence": {"score": 85, "confidence": 70, "note": "Very high.", "supporting_quote": "We shipped it."},
}
FAKE_PROFILE_JSON = json.dumps(FAKE_PROFILE)


def _fake_call(model, max_tokens, system, messages):
    # Change-summary calls have a different system prompt shape; return short prose.
    if "compare two Tone Profile" in (system or ""):
        return "Confidence moved up 15 points; new voice_do added."
    return FAKE_PROFILE_JSON


def test_generate_v1_pending_by_default():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_tone_1.db")
    app_module = _fresh_app(db_path)
    _seed_client(db_path)
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call):
        resp = client.post(
            "/api/clients/1/tone-profiles",
            json={"source_type": "transcript", "source_text": "A" * 500, "context": "default"},
        )
    assert resp.status_code == 200, resp.get_json()
    d = resp.get_json()
    assert d["version"] == 1
    assert d["status"] == "pending"
    assert d["is_active"] == 0
    assert d["parent_version"] is None
    assert json.loads(d["profile_json"])["confidence"]["score"] == 85
    os.remove(db_path)


def test_activate_flips_only_one_active():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_tone_2.db")
    app_module = _fresh_app(db_path)
    _seed_client(db_path)
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call):
        v1 = client.post("/api/clients/1/tone-profiles",
                         json={"source_type": "transcript", "source_text": "A" * 500}).get_json()
        v2 = client.post("/api/clients/1/tone-profiles",
                         json={"source_type": "posts", "source_text": "B" * 500}).get_json()

    assert v2["version"] == 2
    assert v2["parent_version"] == 1

    r1 = client.post(f"/api/clients/1/tone-profiles/{v1['id']}/activate")
    assert r1.status_code == 200 and r1.get_json()["is_active"] == 1

    r2 = client.post(f"/api/clients/1/tone-profiles/{v2['id']}/activate")
    assert r2.status_code == 200 and r2.get_json()["is_active"] == 1

    # v1 should now be flipped off (revert-by-activate: an older version can
    # be reactivated without anything getting deleted).
    lst = client.get("/api/clients/1/tone-profiles?context=default").get_json()
    actives = [p for p in lst if p["is_active"]]
    assert len(actives) == 1 and actives[0]["id"] == v2["id"], actives
    os.remove(db_path)


def test_contexts_are_independent():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_tone_3.db")
    app_module = _fresh_app(db_path)
    _seed_client(db_path)
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call):
        d1 = client.post("/api/clients/1/tone-profiles",
                         json={"source_type": "transcript", "source_text": "A" * 500,
                               "context": "default"}).get_json()
        e1 = client.post("/api/clients/1/tone-profiles",
                         json={"source_type": "posts", "source_text": "B" * 500,
                               "context": "event"}).get_json()
    # Both should be v1 for their own context.
    assert d1["version"] == 1 and e1["version"] == 1
    assert d1["context"] == "default" and e1["context"] == "event"

    # Activating one context's profile does NOT touch the other context.
    client.post(f"/api/clients/1/tone-profiles/{d1['id']}/activate")
    client.post(f"/api/clients/1/tone-profiles/{e1['id']}/activate")

    active_default = client.get("/api/clients/1/tone-profiles/active?context=default").get_json()
    active_event = client.get("/api/clients/1/tone-profiles/active?context=event").get_json()
    assert active_default["id"] == d1["id"]
    assert active_event["id"] == e1["id"]
    os.remove(db_path)


def test_source_mix_accumulates_across_versions():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_tone_4.db")
    app_module = _fresh_app(db_path)
    _seed_client(db_path)
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call):
        client.post("/api/clients/1/tone-profiles",
                    json={"source_type": "transcript", "source_text": "A" * 1000})
        v2 = client.post("/api/clients/1/tone-profiles",
                         json={"source_type": "posts", "source_text": "B" * 600}).get_json()

    mix = json.loads(v2["source_mix"])
    assert mix["spoken_chars"] == 1000, mix
    assert mix["written_chars"] == 600, mix
    os.remove(db_path)


def test_reject_pending_only():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_tone_5.db")
    app_module = _fresh_app(db_path)
    _seed_client(db_path)
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call):
        v1 = client.post("/api/clients/1/tone-profiles",
                         json={"source_type": "transcript", "source_text": "A" * 500}).get_json()

    # Cannot reject an active profile.
    client.post(f"/api/clients/1/tone-profiles/{v1['id']}/activate")
    resp = client.post(f"/api/clients/1/tone-profiles/{v1['id']}/reject")
    assert resp.status_code == 400

    # Can reject a pending profile.
    with patch.object(app_module, "call_anthropic", side_effect=_fake_call):
        v2 = client.post("/api/clients/1/tone-profiles",
                         json={"source_type": "posts", "source_text": "B" * 500}).get_json()
    resp = client.post(f"/api/clients/1/tone-profiles/{v2['id']}/reject")
    assert resp.status_code == 200
    lst = client.get("/api/clients/1/tone-profiles?context=default").get_json()
    v2_row = next(p for p in lst if p["id"] == v2["id"])
    assert v2_row["status"] == "rejected"
    os.remove(db_path)


def test_input_validation():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_tone_6.db")
    app_module = _fresh_app(db_path)
    _seed_client(db_path)
    client = _client(app_module)

    r = client.post("/api/clients/1/tone-profiles",
                    json={"source_type": "essay", "source_text": "A" * 500})
    assert r.status_code == 400

    r = client.post("/api/clients/1/tone-profiles",
                    json={"source_type": "transcript", "source_text": "short"})
    assert r.status_code == 400

    r = client.post("/api/clients/999/tone-profiles",
                    json={"source_type": "transcript", "source_text": "A" * 500})
    assert r.status_code == 404
    os.remove(db_path)


if __name__ == "__main__":
    tests = [
        test_generate_v1_pending_by_default,
        test_activate_flips_only_one_active,
        test_contexts_are_independent,
        test_source_mix_accumulates_across_versions,
        test_reject_pending_only,
        test_input_validation,
    ]
    for t in tests:
        t()
        print(f"PASS: {t.__name__}")
    print("\nALL TESTS PASSED")
