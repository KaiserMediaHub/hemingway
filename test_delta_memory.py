"""
Tests for Phase 4 (Ben's ask, 2026-09-08): rejection reasons, raw voice
examples, and length targeting. Covers:
- rejection reason is stored when rejecting a profile version
- past rejections (with reasons) are fed into the next Delta Analyzer
  analysis prompt
- example_posts accumulates client edits, capped at 3, most recent
- target_length is derived (avg/min/max words) from example_posts
- example_posts/target_length are rendered into the generation system
  prompt when an active profile is in play
- regenerate-again reuses the stored example_posts/target_length rather
  than recomputing

call_anthropic is patched everywhere so tests don't hit the real API.

Run: python test_delta_memory.py
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
}

UPDATED_PROFILE_RESPONSE = {
    "diff_analysis": "Client cut the rhetorical-question opener and tightened sentence length.",
    "rejection_additions": ["opening with a rhetorical question"],
    "summary": "Warm, direct voice -- confirmed sharper.",
    "voice_do": ["state claims plainly"],
    "voice_dont": ["use corporate jargon"],
    "directness": {"score": 85, "confidence": 80, "note": "Very direct.", "supporting_quote": "Just say the thing."},
}


def _seed_client_with_active_profile(db_path, client_id=1, context='default', example_posts=None):
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (?, 'Harris', '')", (client_id,))
    raw.execute(
        "INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, "
        "profile_json, rejection_list, source_mix, status, is_active, example_posts, target_length) "
        "VALUES (?, ?, 3, 'posts', 'x', ?, '[]', ?, 'approved', 1, ?, ?)",
        (client_id, context, json.dumps(CURRENT_PROFILE),
         json.dumps({'spoken_chars': 1000, 'written_chars': 500}),
         json.dumps(example_posts or []),
         json.dumps({}) if not example_posts else json.dumps({
             'avg_words': sum(len(p.split()) for p in example_posts) // len(example_posts),
             'min_words': min(len(p.split()) for p in example_posts),
             'max_words': max(len(p.split()) for p in example_posts),
         }))
    )
    raw.commit()
    raw.close()


def _seed_rejected_version(db_path, client_id=1, context='default', reason='', change_summary=''):
    raw = sqlite3.connect(db_path)
    raw.execute(
        "INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, "
        "profile_json, rejection_list, source_mix, status, is_active, rejection_reason, change_summary) "
        "VALUES (?, ?, 2, 'delta', 'x', ?, '[]', '{}', 'rejected', 0, ?, ?)",
        (client_id, context, json.dumps(CURRENT_PROFILE), reason, change_summary)
    )
    raw.commit()
    raw.close()


LAST_SYSTEM_PROMPT = {}


def _fake_call_anthropic(model, max_tokens, system, messages):
    if 'voice analyst refining' in system:
        LAST_SYSTEM_PROMPT['analysis'] = system
        return json.dumps(UPDATED_PROFILE_RESPONSE)
    if 'ACTIVE TONE PROFILE' in system:
        LAST_SYSTEM_PROMPT['regen'] = system
        return 'Regenerated post using the updated voice.'
    return 'fallback response'


def test_rejection_reason_stored_via_phase1_route():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_mem_1.db")
    app_module = _fresh_app(db_path)
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, 'Harris', '')")
    raw.execute(
        "INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, "
        "profile_json, status, is_active) VALUES (1, 'default', 1, 'posts', 'x', '{}', 'pending', 0)"
    )
    raw.commit()
    raw.close()
    client = _client(app_module)

    resp = client.post("/api/clients/1/tone-profiles/1/reject", json={"reason": "too formal, he'd never write it this way"})
    assert resp.status_code == 200, resp.get_json()

    check_conn = sqlite3.connect(db_path)
    row = check_conn.execute("SELECT status, rejection_reason FROM tone_profiles WHERE id = 1").fetchone()
    check_conn.close()
    assert row[0] == 'rejected'
    assert row[1] == "too formal, he'd never write it this way"
    os.remove(db_path)


def test_reject_with_no_reason_defaults_to_empty_string():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_mem_2.db")
    app_module = _fresh_app(db_path)
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, 'Harris', '')")
    raw.execute(
        "INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, "
        "profile_json, status, is_active) VALUES (1, 'default', 1, 'posts', 'x', '{}', 'pending', 0)"
    )
    raw.commit()
    raw.close()
    client = _client(app_module)

    resp = client.post("/api/clients/1/tone-profiles/1/reject")  # no body at all
    assert resp.status_code == 200, resp.get_json()
    check_conn = sqlite3.connect(db_path)
    row = check_conn.execute("SELECT rejection_reason FROM tone_profiles WHERE id = 1").fetchone()
    check_conn.close()
    assert row[0] == ''
    os.remove(db_path)


def test_delta_analysis_prompt_includes_past_rejection_reasons():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_mem_3.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path)
    _seed_rejected_version(db_path, reason="way too corporate, kill the jargon", change_summary="Tried raising formality score")
    client = _client(app_module)

    LAST_SYSTEM_PROMPT.clear()
    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        resp = client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": "Just say the thing. We launched." * 2,
        })
    assert resp.status_code == 200, resp.get_json()
    analysis_prompt = LAST_SYSTEM_PROMPT.get('analysis', '')
    assert "PREVIOUSLY REJECTED" in analysis_prompt
    assert "way too corporate, kill the jargon" in analysis_prompt
    assert "Tried raising formality score" in analysis_prompt
    os.remove(db_path)


def test_example_posts_accumulate_capped_at_three():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_mem_4.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path, example_posts=["Edit one text here.", "Edit two text here."])
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        resp = client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": "Edit three text here, brand new.",
        })
    tp = resp.get_json()["tone_profile"]
    examples = json.loads(tp["example_posts"])
    assert examples == ["Edit one text here.", "Edit two text here.", "Edit three text here, brand new."]

    # A 4th delta run should push out the oldest, keeping only the 3 most recent.
    lookup_conn = sqlite3.connect(db_path)
    active_row = lookup_conn.execute(
        "SELECT id FROM tone_profiles WHERE client_id=1 AND context='default' ORDER BY version DESC LIMIT 1"
    ).fetchone()
    lookup_conn.close()
    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        client.post(f"/api/clients/1/tone-profiles/{active_row[0]}/activate")
        resp2 = client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": "Edit four text here, even newer.",
        })
    tp2 = resp2.get_json()["tone_profile"]
    examples2 = json.loads(tp2["example_posts"])
    assert len(examples2) == 3, examples2
    assert examples2 == ["Edit two text here.", "Edit three text here, brand new.", "Edit four text here, even newer."]
    os.remove(db_path)


def test_target_length_derived_from_example_posts():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_mem_5.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path)
    client = _client(app_module)

    client_edit = "one two three four five six seven eight nine ten"  # 10 words
    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        resp = client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": client_edit,
        })
    tp = resp.get_json()["tone_profile"]
    tlen = json.loads(tp["target_length"])
    assert tlen == {"avg_words": 10, "min_words": 10, "max_words": 10}, tlen
    os.remove(db_path)


def test_regen_system_prompt_includes_examples_and_length():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_mem_6.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path, example_posts=["A short real client post right here."])
    client = _client(app_module)

    LAST_SYSTEM_PROMPT.clear()
    client_edit = "one two three four five"
    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": client_edit,
        })
    regen_prompt = LAST_SYSTEM_PROMPT.get('regen', '')
    assert "REAL EXAMPLES OF THIS CLIENT'S OWN VOICE" in regen_prompt
    assert "A short real client post right here." in regen_prompt
    assert "TARGET LENGTH" in regen_prompt
    os.remove(db_path)


def test_regen_does_not_leak_current_pair_answer():
    """Bug found by Ben in real use, 2026-09-08: the regeneration attempt was
    just repeating the client's own edit verbatim, regardless of the post's
    actual topic. Root cause: THIS pair's client_edit gets merged into
    example_posts before the regen call runs, so the model was literally
    handed the answer as a 'follow this' example. This must never happen --
    the regen prompt must not contain the client_edit for the pair currently
    being tested, even when it's the ONLY example on file (the worst case,
    since with nothing else to draw on the model has maximum incentive to
    just paste the one thing it was shown)."""
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_mem_8.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path)  # no example_posts on file yet
    client = _client(app_module)

    LAST_SYSTEM_PROMPT.clear()
    client_edit = "This is the exact answer the client wrote, must not leak."
    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": client_edit,
        })
    regen_prompt = LAST_SYSTEM_PROMPT.get('regen', '')
    assert client_edit not in regen_prompt, "current pair's own client edit leaked into its own regen test"
    os.remove(db_path)


def test_regenerate_again_reuses_stored_examples_not_recomputed():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_mem_7.db")
    app_module = _fresh_app(db_path)
    _seed_client_with_active_profile(db_path, example_posts=["Original stored example post text."])
    client = _client(app_module)

    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        resp = client.post("/api/clients/1/tone-profiles/delta", json={
            "context": "default",
            "original_post": "This is the original post about our launch." * 2,
            "client_edit": "A totally new client edit example.",
        })
    delta_id = resp.get_json()["delta"]["id"]

    LAST_SYSTEM_PROMPT.clear()
    with patch.object(app_module, "call_anthropic", side_effect=_fake_call_anthropic):
        resp2 = client.post(f"/api/clients/1/tone-profiles/deltas/{delta_id}/regenerate-again")
    assert resp2.status_code == 200, resp2.get_json()
    regen_prompt = LAST_SYSTEM_PROMPT.get('regen', '')
    # Prior, legitimate example should still be there...
    assert "Original stored example post text." in regen_prompt
    # ...but THIS delta's own client_edit is the answer being tested against
    # and must NOT leak into the regeneration prompt (bug found by Ben in
    # real use, 2026-09-08: regenerations were just parroting the client's
    # actual edit back because it was sitting in the prompt as a "follow
    # this" example).
    assert "A totally new client edit example." not in regen_prompt
    os.remove(db_path)


if __name__ == "__main__":
    tests = [
        test_rejection_reason_stored_via_phase1_route,
        test_reject_with_no_reason_defaults_to_empty_string,
        test_delta_analysis_prompt_includes_past_rejection_reasons,
        test_example_posts_accumulate_capped_at_three,
        test_target_length_derived_from_example_posts,
        test_regen_system_prompt_includes_examples_and_length,
        test_regen_does_not_leak_current_pair_answer,
        test_regenerate_again_reuses_stored_examples_not_recomputed,
    ]
    for t in tests:
        t()
        print(f"PASS: {t.__name__}")
    print("\nALL TESTS PASSED")
