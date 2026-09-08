"""
Tests for Phase 3 Delta Analyzer (Ben's ask, 2026-09-03). Covers:
- requires an active profile before running
- proposes a new pending version with correct parent/version numbering
- rejection_list merges (union, dedup) rather than replaces
- source_mix grows written_chars by the client edit's length
- regeneration attempt is stored on tone_deltas
- regenerate-again retries only the regeneration, not the whole analysis
- input validation

call_anthropic is patched everywhere so tests don't hit the real API.

Run: python test_delta_analyzer.py
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


CURRENT_PROFILE = {
    "summary": "Warm, direct voice.",
    "voice_do": ["state claims plainly"],
    "voice_dont": ["use corporate jargon"],
    "directness": {"score": 70, "confidence": 60, "note": "Fairly direct.", "supporting_quote": "We shipped it."},
    "confidence": {"score": 60, "confidence": 50, "note": "Moderate confidence.", "supporting_quote": ""},
}

UPDATED_PROFILE_RESPONSE = {
    "diff_analysis": "Client cut the rhetorical-question opener and tightened sentence length.",
    "rejection_additions": ["opening with a rhetorical question", "the phrase 'at the end of the day'"],
    "summary": "Warm, direct voice -- confirmed sharper and more concise than prior estimate.",
    "voice_do": ["state claims plainly", "open with the claim, not a question"],
    "voice_dont": ["use corporate jargon", "open with a rhetorical question"],
    "directness": {"score": 85, "confidence": 80, "note": "Very direct, confirmed by edit.", "supporting_quote": "Just say the thing."},
    "confidence": {"score": 60, "confidence": 50, "note": "Moderate confidence.", "supporting_quote": ""},
}


def _seed_client_with_active_profile(db_path, client_id=1, context='default', rejection_list=None):
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (?, 'Harris', '')", (client_id,))
    raw.execute(
        "INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, "
        "profile_json, rejection_list, source_mix, status, is_active) "
        "VALUES (?, ?, 3, 'posts', 'x', ?, ?, ?, 'approved', 1)",
        (client_id, context, json.dumps(CURRENT_PROFILE),
         json.dumps(rejection_list or ["never say 'game-changer'"]),
         json.dumps({'spoken_chars': 1000, 'written_chars': 500}))
    )
    raw.commit()
    raw.close()


def _fake_call_anthropic(model, max_tokens, system, messages):
    if 'voice analyst refining' in system:
        return json.dumps(UPDATED_PROFILE_RESPONSE)
    if 'ACTIVE TONE PROFILE' in system:
        return 'Regenerated post using the updated voice.'
    return 'fallback response'


def test_requires_active_profile():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_delta_1.db")
    app_module = _fresh_app(db_path)
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, 'NoProfile', '')")
    raw.commit()
    raw.close()
    client = _client(app_module)

    resp = client.post("/api/clients/1/tone-profiles/delta", json={
        "context": "default",
        "original_post": "A" * 30,
        "client_edit": "B" * 30,
    })
    assert resp.status_code == 400, resp.get_json()
    assert "No active Tone Profile" in resp.get_json()["error"]["message"]
    os.remove(db_path)


def test_input_validation():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_delta_2.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path)
    client = _client(app_module)

    resp = client.post("/api/clients/1/tone-profiles/delta", json={
        "context": "default", "original_post": "short", "client_edit": "B" * 30,
    })
    assert resp.status_code == 400
    os.remove(db_path)


def test_proposes_new_pending_version_with_correct_parent():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_delta_3.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path)
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        resp = client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": "Just say the thing. We launched." * 2,
        })
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    tp = data["tone_profile"]
    assert tp["version"] == 4, tp
    assert tp["parent_version"] == 3
    assert tp["status"] == "pending"
    assert tp["is_active"] == 0
    assert tp["source_type"] == "delta"
    assert tp["change_summary"] == UPDATED_PROFILE_RESPONSE["diff_analysis"]
    os.remove(db_path)


def test_rejection_list_merges_not_replaces():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_delta_4.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path, rejection_list=["never say 'game-changer'"])
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        resp = client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": "Just say the thing. We launched." * 2,
        })
    tp = resp.get_json()["tone_profile"]
    rejections = json.loads(tp["rejection_list"])
    assert "never say 'game-changer'" in rejections, "old rejection lost"
    assert "opening with a rhetorical question" in rejections, "new rejection missing"
    assert "the phrase 'at the end of the day'" in rejections
    assert len(rejections) == 3, rejections
    os.remove(db_path)


def test_source_mix_grows_written_chars_by_client_edit_length():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_delta_5.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path)
    client = _client(app_module)

    client_edit = "Just say the thing. We launched." * 2
    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        resp = client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": client_edit,
        })
    tp = resp.get_json()["tone_profile"]
    mix = json.loads(tp["source_mix"])
    assert mix["spoken_chars"] == 1000
    assert mix["written_chars"] == 500 + len(client_edit), mix
    os.remove(db_path)


def test_regenerated_attempt_stored_on_delta_row():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_delta_6.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path)
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        resp = client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": "Just say the thing. We launched." * 2,
        })
    delta = resp.get_json()["delta"]
    assert delta["regenerated_attempt"] == "Regenerated post using the updated voice."
    assert delta["resulting_version"] == 4
    os.remove(db_path)


def test_regenerate_again_only_retries_regeneration():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_delta_7.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path)
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        resp = client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": "Just say the thing. We launched." * 2,
        })
    delta_id = resp.get_json()["delta"]["id"]

    call_count = {"analysis": 0, "regen": 0}
    def counting_fake(model, max_tokens, system, messages):
        if 'voice analyst refining' in system:
            call_count["analysis"] += 1
            return json.dumps(UPDATED_PROFILE_RESPONSE)
        call_count["regen"] += 1
        return "Second regeneration attempt."

    with patch.object(app_module, "call_anthropic", side_effect=counting_fake):
        resp2 = client.post(f"/api/clients/1/tone-profiles/deltas/{delta_id}/regenerate-again")
    assert resp2.status_code == 200, resp2.get_json()
    assert call_count["analysis"] == 0, "regenerate-again must NOT re-run the diff analysis"
    assert call_count["regen"] == 1
    assert resp2.get_json()["regenerated_attempt"] == "Second regeneration attempt."
    os.remove(db_path)


def test_activate_via_existing_phase1_route_works_on_delta_version():
    """The Yes/No gap-closed buttons reuse Phase 1's activate/reject routes
    unchanged -- this proves a delta-sourced pending version activates
    cleanly and correctly deactivates the old one."""
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_delta_8.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path)
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        resp = client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": "Just say the thing. We launched." * 2,
        })
    new_id = resp.get_json()["tone_profile"]["id"]

    activate_resp = client.post(f"/api/clients/1/tone-profiles/{new_id}/activate")
    assert activate_resp.status_code == 200
    assert activate_resp.get_json()["is_active"] == 1

    active = client.get("/api/clients/1/tone-profiles/active?context=default").get_json()
    assert active["id"] == new_id
    assert active["version"] == 4
    os.remove(db_path)


def test_list_deltas():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_delta_9.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path)
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": "Just say the thing. We launched." * 2,
        })
    resp = client.get("/api/clients/1/tone-profiles/deltas?context=default")
    assert resp.status_code == 200
    lst = resp.get_json()
    assert len(lst) == 1
    assert lst[0]["resulting_version"] == 4
    os.remove(db_path)


if __name__ == "__main__":
    tests = [
        test_requires_active_profile,
        test_input_validation,
        test_proposes_new_pending_version_with_correct_parent,
        test_rejection_list_merges_not_replaces,
        test_source_mix_grows_written_chars_by_client_edit_length,
        test_regenerated_attempt_stored_on_delta_row,
        test_regenerate_again_only_retries_regeneration,
        test_activate_via_existing_phase1_route_works_on_delta_version,
        test_list_deltas,
    ]
    for t in tests:
        t()
        print(f"PASS: {t.__name__}")
    print("\nALL TESTS PASSED")
