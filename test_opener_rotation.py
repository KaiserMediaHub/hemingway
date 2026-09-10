"""
Tests for Phase 5 opener rotation + opener library (Ben's ask, 2026-09-09):
"I'm TRYING so hard to please this client... I need help writing in a few
different openings but all sounding like Tim." Each Hemingway generation call
is otherwise fully stateless with zero awareness of any other post -- even
posts written earlier in the SAME batch -- which is the root cause of
repetitive openers. This adds:

  - opener_shapes on the Tone Profile (reusable structural templates)
  - recent_openers: last few real posts for this client/context, PLUS
    whatever's already been written earlier in the same batch
  - opener_library: a manually-curated bank of real, human-approved openers
    (Harris posts via Hey Orca, not Postiz -- no automatic publish signal,
    so this is a deliberate "paste it in when you know it's good" upload)

Covers:
- _extract_opening_line heuristic
- get_recent_openers / get_opener_library helpers
- opener_library CRUD routes (add/list/delete, validation, 404s)
- render_tone_profile_for_prompt renders opener_shapes
- render_opener_context output format
- batch-loop accumulation: post 2 of a batch sees post 1's opener as "recently used"

call_anthropic is patched everywhere so tests don't hit the real API.

Run: python test_opener_rotation.py
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


PROFILE_WITH_SHAPES = {
    "summary": "Warm, direct, unhedged first-person voice.",
    "voice_do": ["state claims without hedging"],
    "voice_dont": ["use corporate jargon"],
    "opener_shapes": [
        "On this [job type], we [specific action].",
        "There's a reason [detail] never shows up in photos.",
    ],
    "directness": {"score": 90, "confidence": 85, "note": "States claims without hedging.", "supporting_quote": "We shipped it."},
}


# --- Pure prompt-layer tests (no server) ---

def test_prompt_renders_opener_shapes():
    from prompts import build_system_prompt
    system = build_system_prompt('conversational', client_rules='', active_tone_profile=PROFILE_WITH_SHAPES)
    assert 'OPENER SHAPES' in system
    assert 'On this [job type], we [specific action].' in system
    assert "There's a reason [detail] never shows up in photos." in system


def test_prompt_skips_opener_shapes_block_when_none_present():
    from prompts import build_system_prompt
    profile_no_shapes = {k: v for k, v in PROFILE_WITH_SHAPES.items() if k != 'opener_shapes'}
    system = build_system_prompt('conversational', client_rules='', active_tone_profile=profile_no_shapes)
    assert 'OPENER SHAPES' not in system


def test_render_opener_context_recent_only():
    from prompts import render_opener_context
    ctx = render_opener_context(recent_openers=["We just wrapped up a re-roof."], library_openers=None)
    assert 'RECENTLY USED OPENERS' in ctx
    assert 'We just wrapped up a re-roof.' in ctx
    assert 'APPROVED OPENERS' not in ctx


def test_render_opener_context_library_only():
    from prompts import render_opener_context
    ctx = render_opener_context(recent_openers=None, library_openers=["This started as a small leak."])
    assert 'APPROVED OPENERS' in ctx
    assert 'This started as a small leak.' in ctx
    assert 'RECENTLY USED' not in ctx


def test_render_opener_context_empty_when_nothing_passed():
    from prompts import render_opener_context
    assert render_opener_context(recent_openers=None, library_openers=None) == ''
    assert render_opener_context(recent_openers=[], library_openers=[]) == ''
    assert render_opener_context(recent_openers=['   '], library_openers=None) == ''


def test_render_opener_context_library_capped_at_ten():
    from prompts import render_opener_context
    many = [f"Opener number {i}." for i in range(15)]
    ctx = render_opener_context(recent_openers=None, library_openers=many)
    for i in range(10):
        assert f"Opener number {i}." in ctx
    assert "Opener number 12." not in ctx


def test_opener_context_reaches_system_prompt_when_profile_active():
    from prompts import build_system_prompt
    system = build_system_prompt(
        'conversational', client_rules='', active_tone_profile=PROFILE_WITH_SHAPES,
        recent_openers=["We just wrapped up a re-roof."],
        library_openers=["This started as a small leak."],
    )
    assert 'RECENTLY USED OPENERS' in system
    assert 'We just wrapped up a re-roof.' in system
    assert 'APPROVED OPENERS' in system
    assert 'This started as a small leak.' in system


def test_opener_context_absent_when_no_active_profile():
    """recent_openers/library_openers only matter once a profile is active --
    matches the existing precedence rule (profile replaces style_rules)."""
    from prompts import build_system_prompt
    system = build_system_prompt(
        'conversational', client_rules='USE PLAIN LANGUAGE', active_tone_profile=None,
        recent_openers=["We just wrapped up a re-roof."],
    )
    assert 'RECENTLY USED OPENERS' not in system


# --- Forced opener-shape assignment (Ben's ask, 2026-09-10) ---
# Production feedback: the original "pick one shape, rotate" instruction was
# too soft -- across a real 10-post Harris batch, the model used only 2
# distinct intros, and one of them ("Here we are...") wasn't even one of the
# 25 shapes. Fix: the caller now deterministically assigns exactly one shape
# per post rather than leaving the choice to the model.

def test_assigned_shape_renders_forced_instruction_not_full_list():
    from prompts import build_system_prompt
    system = build_system_prompt(
        'conversational', client_rules='', active_tone_profile=PROFILE_WITH_SHAPES,
        assigned_opener_shape="On this [job type], we [specific action].",
    )
    assert 'OPENER SHAPE FOR THIS POST' in system
    assert 'On this [job type], we [specific action].' in system
    # The other shape from the profile must NOT be dumped into the prompt --
    # forced-assignment mode shows only the one assigned shape, not the menu.
    assert "There's a reason [detail] never shows up in photos." not in system


def test_no_assigned_shape_falls_back_to_full_list_and_soft_instruction():
    """Regression guard: single-post callers that don't pass
    assigned_opener_shape (or profiles with no opener_shapes at all) keep the
    old list-plus-soft-rotate rendering unchanged."""
    from prompts import build_system_prompt
    system = build_system_prompt(
        'conversational', client_rules='', active_tone_profile=PROFILE_WITH_SHAPES,
        assigned_opener_shape=None,
    )
    assert 'OPENER SHAPES (Ben\'s ask, 2026-09-09)' in system
    assert 'OPENER SHAPE FOR THIS POST' not in system
    assert 'On this [job type], we [specific action].' in system
    assert "There's a reason [detail] never shows up in photos." in system


def test_generate_route_assigns_different_shape_to_each_post_in_batch():
    """The actual production fix: with a 2-shape profile and a 2-post batch,
    each post must get a DIFFERENT assigned shape -- not left to chance."""
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_opener_10.db")
    app_module = _fresh_app(db_path)

    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, 'Harris', '')")
    raw.execute(
        "INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, "
        "profile_json, status, is_active) VALUES (1, 'default', 1, 'posts', 'x', ?, 'approved', 1)",
        (json.dumps(PROFILE_WITH_SHAPES),)
    )
    raw.commit()
    raw.close()

    client = _client(app_module)
    draft_systems = []

    def fake(model, max_tokens, system, messages):
        user_content = messages[0]['content']
        if 'DRAFT POST TO REVIEW:' in user_content:
            after = user_content[user_content.index('DRAFT POST TO REVIEW:'):]
            body_start = after.index('---\n') + len('---\n')
            rest = after[body_start:]
            body_end = rest.index('\n---')
            return rest[:body_end]
        draft_systems.append(system)
        return "A generated post.\n\nBody text follows."

    with patch.object(app_module, "call_anthropic", side_effect=fake):
        r = client.post("/api/generate", json={
            "clientId": 1,
            "transcript": "Post 1:\nFirst topic.\n\nPost 2:\nSecond topic.",
            "style": "conversational",
            "length": "short",
            "format": "plain",
            "tone_context": "default",
        })
        assert r.status_code == 200
        r.get_data()

    assert len(draft_systems) == 2
    shape_a = "On this [job type], we [specific action]."
    shape_b = "There's a reason [detail] never shows up in photos."
    post0_has_a = shape_a in draft_systems[0]
    post0_has_b = shape_b in draft_systems[0]
    post1_has_a = shape_a in draft_systems[1]
    post1_has_b = shape_b in draft_systems[1]

    assert post0_has_a != post0_has_b, "post 0 must be assigned exactly one shape"
    assert post1_has_a != post1_has_b, "post 1 must be assigned exactly one shape"
    assert (post0_has_a, post0_has_b) != (post1_has_a, post1_has_b), (
        "post 0 and post 1 were assigned the SAME shape -- rotation isn't working"
    )
    for s in draft_systems:
        assert 'OPENER SHAPE FOR THIS POST' in s


def test_rewrite_post_assigns_a_shape_when_shapes_present():
    """Single-post rewrite has no batch to round-robin against, but should
    still force ONE randomly-chosen shape rather than leaving the model a
    free menu of 25 to (in practice) mostly ignore."""
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_opener_11.db")
    app_module = _fresh_app(db_path)

    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, 'Harris', '')")
    raw.execute(
        "INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, "
        "profile_json, status, is_active) VALUES (1, 'default', 1, 'posts', 'x', ?, 'approved', 1)",
        (json.dumps(PROFILE_WITH_SHAPES),)
    )
    raw.execute("INSERT INTO batches (id, client_id, transcript_raw, style, length, context) VALUES (1, 1, 'x', 'conversational', 'short', '')")
    raw.execute("INSERT INTO posts (id, batch_id, title, body, section_body) VALUES (1, 1, 'T1', 'Old body.', 'sec1')")
    raw.commit()
    raw.close()

    client = _client(app_module)
    captured = []

    def fake(model, max_tokens, system, messages):
        captured.append(system)
        return "Rewritten post."

    with patch.object(app_module, "call_anthropic", side_effect=fake):
        resp = client.post("/api/posts/1/rewrite", json={})
    assert resp.status_code == 200, resp.get_json()

    joined = '\n'.join(captured)
    assert 'OPENER SHAPE FOR THIS POST' in joined
    shape_a = "On this [job type], we [specific action]."
    shape_b = "There's a reason [detail] never shows up in photos."
    assert (shape_a in joined) or (shape_b in joined)


# --- _extract_opening_line heuristic ---

def test_extract_opening_line_short_first_line():
    from app import _extract_opening_line
    assert _extract_opening_line("We just wrapped up a re-roof.\n\nMore text here.") == "We just wrapped up a re-roof."


def test_extract_opening_line_truncates_long_first_line_at_sentence():
    from app import _extract_opening_line
    text = "This is the first sentence of a much longer opening line. It keeps going with more detail after that.\n\nSecond paragraph."
    result = _extract_opening_line(text)
    assert result == "This is the first sentence of a much longer opening line."


def test_extract_opening_line_empty_input():
    from app import _extract_opening_line
    assert _extract_opening_line('') == ''
    assert _extract_opening_line(None) == ''


# --- get_recent_openers / get_opener_library helpers ---

def test_get_recent_openers_joins_through_batches():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_opener_1.db")
    app_module = _fresh_app(db_path)
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name) VALUES (1, 'Harris')")
    raw.execute("INSERT INTO batches (id, client_id, transcript_raw, style, length) VALUES (1, 1, 'x', 'conversational', 'short')")
    raw.execute("INSERT INTO posts (id, batch_id, title, body, section_body) VALUES (1, 1, 'T1', 'We just wrapped up a re-roof.\n\nMore.', 'sec1')")
    raw.execute("INSERT INTO posts (id, batch_id, title, body, section_body) VALUES (2, 1, 'T2', 'There is a reason this matters.\n\nMore.', 'sec2')")
    # A post for a DIFFERENT client must not leak in.
    raw.execute("INSERT INTO clients (id, name) VALUES (2, 'OtherClient')")
    raw.execute("INSERT INTO batches (id, client_id, transcript_raw, style, length) VALUES (2, 2, 'x', 'conversational', 'short')")
    raw.execute("INSERT INTO posts (id, batch_id, title, body, section_body) VALUES (3, 2, 'T3', 'This should not appear.\n\nMore.', 'sec3')")
    raw.commit()
    raw.close()

    with app_module.app.app_context():
        openers = app_module.get_recent_openers(1, 'default', limit=3)
    assert "We just wrapped up a re-roof." in openers
    assert "There is a reason this matters." in openers
    assert not any('should not appear' in o for o in openers)
    os.remove(db_path)


def test_get_recent_openers_respects_limit():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_opener_2.db")
    app_module = _fresh_app(db_path)
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name) VALUES (1, 'Harris')")
    raw.execute("INSERT INTO batches (id, client_id, transcript_raw, style, length) VALUES (1, 1, 'x', 'conversational', 'short')")
    for i in range(5):
        raw.execute(
            "INSERT INTO posts (id, batch_id, title, body, section_body) VALUES (?, 1, ?, ?, 'sec')",
            (i + 1, f"T{i}", f"Opener {i}.\n\nMore.")
        )
    raw.commit()
    raw.close()

    with app_module.app.app_context():
        openers = app_module.get_recent_openers(1, 'default', limit=3)
    assert len(openers) == 3
    os.remove(db_path)


def test_get_opener_library_scoped_by_context():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_opener_3.db")
    app_module = _fresh_app(db_path)
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name) VALUES (1, 'Harris')")
    raw.execute("INSERT INTO opener_library (client_id, context, opener_text) VALUES (1, 'default', 'Default context opener.')")
    raw.execute("INSERT INTO opener_library (client_id, context, opener_text) VALUES (1, 'event', 'Event context opener.')")
    raw.commit()
    raw.close()

    with app_module.app.app_context():
        default_openers = app_module.get_opener_library(1, 'default')
        event_openers = app_module.get_opener_library(1, 'event')
    assert default_openers == ['Default context opener.']
    assert event_openers == ['Event context opener.']
    os.remove(db_path)


# --- Opener library CRUD routes ---

def test_add_list_delete_opener_library_entry():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_opener_4.db")
    app_module = _fresh_app(db_path)
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name) VALUES (1, 'Harris')")
    raw.commit()
    raw.close()
    client = _client(app_module)

    resp = client.post("/api/clients/1/opener-library", json={"opener_text": "We just wrapped up a re-roof."})
    assert resp.status_code == 200, resp.get_json()
    entry_id = resp.get_json()["id"]
    assert resp.get_json()["opener_text"] == "We just wrapped up a re-roof."
    assert resp.get_json()["context"] == "default"

    resp = client.get("/api/clients/1/opener-library?context=default")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 1

    resp = client.delete(f"/api/clients/1/opener-library/{entry_id}")
    assert resp.status_code == 200

    resp = client.get("/api/clients/1/opener-library?context=default")
    assert resp.get_json() == []
    os.remove(db_path)


def test_add_opener_library_rejects_short_text():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_opener_5.db")
    app_module = _fresh_app(db_path)
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name) VALUES (1, 'Harris')")
    raw.commit()
    raw.close()
    client = _client(app_module)

    resp = client.post("/api/clients/1/opener-library", json={"opener_text": "Hi"})
    assert resp.status_code == 400
    os.remove(db_path)


def test_add_opener_library_404_on_unknown_client():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_opener_6.db")
    app_module = _fresh_app(db_path)
    client = _client(app_module)

    resp = client.post("/api/clients/999/opener-library", json={"opener_text": "We just wrapped up a re-roof."})
    assert resp.status_code == 404
    os.remove(db_path)


def test_delete_opener_library_404_on_wrong_client():
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_opener_7.db")
    app_module = _fresh_app(db_path)
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name) VALUES (1, 'Harris')")
    raw.execute("INSERT INTO clients (id, name) VALUES (2, 'OtherClient')")
    raw.execute("INSERT INTO opener_library (id, client_id, context, opener_text) VALUES (1, 1, 'default', 'We just wrapped up a re-roof.')")
    raw.commit()
    raw.close()
    client = _client(app_module)

    # Try to delete client 1's entry via client 2's URL -- must 404, not delete.
    resp = client.delete("/api/clients/2/opener-library/1")
    assert resp.status_code == 404

    resp = client.get("/api/clients/1/opener-library?context=default")
    assert len(resp.get_json()) == 1, "entry must still exist -- wrong-client delete must not succeed"
    os.remove(db_path)


# --- Batch-loop accumulation (the actual repetition fix) ---

def test_batch_loop_second_post_sees_first_posts_opener():
    """The core fix: within ONE /api/generate call writing multiple posts,
    post 2's system prompt must know what post 1 already opened with, even
    though post 1 wasn't in the database yet when post 2's prompt was built
    (it's accumulated in-memory as batch_openers, not re-queried)."""
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_opener_8.db")
    app_module = _fresh_app(db_path)

    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, 'Harris', '')")
    raw.execute(
        "INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, "
        "profile_json, status, is_active) VALUES (1, 'default', 1, 'posts', 'x', ?, 'approved', 1)",
        (json.dumps(PROFILE_WITH_SHAPES),)
    )
    raw.commit()
    raw.close()

    client = _client(app_module)

    captured_systems = []
    draft_call_n = {"n": 0}

    def fake(model, max_tokens, system, messages):
        captured_systems.append(system)
        user_content = messages[0]['content']
        if 'DRAFT POST TO REVIEW:' in user_content:
            # Review pass: echo the draft back UNCHANGED, so the opener
            # tracked for this post is deterministic (whatever the draft
            # call returned), not confused with a draft call by miscounting.
            after = user_content[user_content.index('DRAFT POST TO REVIEW:'):]
            body_start = after.index('---\n') + len('---\n')
            rest = after[body_start:]
            body_end = rest.index('\n---')
            return rest[:body_end]
        # Draft pass
        draft_call_n["n"] += 1
        return f"Distinct opening line number {draft_call_n['n']}.\n\nBody text follows."

    with patch.object(app_module, "call_anthropic", side_effect=fake):
        r = client.post("/api/generate", json={
            "clientId": 1,
            "transcript": "Post 1:\nFirst topic.\n\nPost 2:\nSecond topic.",
            "style": "conversational",
            "length": "short",
            "format": "plain",
            "tone_context": "default",
        })
        assert r.status_code == 200
        r.get_data()

    # captured_systems order: [post0 draft, post0 review, post1 draft, post1 review].
    # Post 1's draft-call system prompt (captured_systems[2]) is the one that
    # must carry post 0's tracked opener via batch_openers.
    assert 'Distinct opening line number 1.' in captured_systems[2], (
        "post 1's opener never reached post 2's draft system prompt -- batch_openers "
        "accumulation isn't wiring through"
    )
    os.remove(db_path)


def test_generate_route_fetches_recent_and_library_openers_before_stream():
    """Regression guard for the pre-stream fetch pattern (recent_openers /
    library_openers must be fetched before stream() the same way
    active_tone_profile and global_style already are, since g.db is gone
    once Flask hands off the streaming response)."""
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_opener_9.db")
    app_module = _fresh_app(db_path)

    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, 'Harris', '')")
    raw.execute(
        "INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, "
        "profile_json, status, is_active) VALUES (1, 'default', 1, 'posts', 'x', ?, 'approved', 1)",
        (json.dumps(PROFILE_WITH_SHAPES),)
    )
    raw.execute("INSERT INTO batches (id, client_id, transcript_raw, style, length) VALUES (1, 1, 'x', 'conversational', 'short')")
    raw.execute("INSERT INTO posts (id, batch_id, title, body, section_body) VALUES (1, 1, 'Old', 'A previously used opener.\n\nMore.', 'sec')")
    raw.execute("INSERT INTO opener_library (client_id, context, opener_text) VALUES (1, 'default', 'A confirmed Hey Orca opener.')")
    raw.commit()
    raw.close()

    client = _client(app_module)
    captured = []

    def fake(model, max_tokens, system, messages):
        captured.append(system)
        return "New post body."

    with patch.object(app_module, "call_anthropic", side_effect=fake):
        r = client.post("/api/generate", json={
            "clientId": 1,
            "transcript": "Post 1:\nA topic.",
            "style": "conversational",
            "length": "short",
            "format": "plain",
            "tone_context": "default",
        })
        assert r.status_code == 200
        r.get_data()

    joined = '\n'.join(captured)
    assert 'A previously used opener.' in joined
    assert 'A confirmed Hey Orca opener.' in joined
    os.remove(db_path)


if __name__ == "__main__":
    tests = [
        test_prompt_renders_opener_shapes,
        test_prompt_skips_opener_shapes_block_when_none_present,
        test_render_opener_context_recent_only,
        test_render_opener_context_library_only,
        test_render_opener_context_empty_when_nothing_passed,
        test_render_opener_context_library_capped_at_ten,
        test_opener_context_reaches_system_prompt_when_profile_active,
        test_opener_context_absent_when_no_active_profile,
        test_assigned_shape_renders_forced_instruction_not_full_list,
        test_no_assigned_shape_falls_back_to_full_list_and_soft_instruction,
        test_generate_route_assigns_different_shape_to_each_post_in_batch,
        test_rewrite_post_assigns_a_shape_when_shapes_present,
        test_extract_opening_line_short_first_line,
        test_extract_opening_line_truncates_long_first_line_at_sentence,
        test_extract_opening_line_empty_input,
        test_get_recent_openers_joins_through_batches,
        test_get_recent_openers_respects_limit,
        test_get_opener_library_scoped_by_context,
        test_add_list_delete_opener_library_entry,
        test_add_opener_library_rejects_short_text,
        test_add_opener_library_404_on_unknown_client,
        test_delete_opener_library_404_on_wrong_client,
        test_batch_loop_second_post_sees_first_posts_opener,
        test_generate_route_fetches_recent_and_library_openers_before_stream,
    ]
    for t in tests:
        t()
        print(f"PASS: {t.__name__}")
    print("\nALL TESTS PASSED")
