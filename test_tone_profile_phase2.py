"""
Phase 2 tests (Ben's ask 2026-08-27): active Tone Profile reaches the prompt
and REPLACES the manual style_rules / reference-copy layer when present.
Also proves the /api/generate route uses the active profile end-to-end.

Run: python test_tone_profile_phase2.py
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


PROFILE = {
    "summary": "Warm, direct, unhedged first-person voice.",
    "voice_do": ["state claims without hedging", "use short opening beats"],
    "voice_dont": ["use corporate jargon", "end on 'what do you think?'"],
    "directness": {"score": 90, "confidence": 85, "note": "States claims without hedging.", "supporting_quote": "We shipped it."},
    "concreteness": {"score": 70, "confidence": 75, "note": "Prefers concrete examples over abstractions.", "supporting_quote": "Cut cycle time 40%."},
    "joy":         {"score": 45, "confidence": 30, "note": "Occasionally warm.", "supporting_quote": "That was a fun week."},
    "humor":       {"score": 20, "confidence": 80, "note": "Rarely leans on humor.", "supporting_quote": ""},
}


# --- Prompt-layer tests (pure, no server) ---

def test_prompt_includes_profile_when_active():
    from prompts import build_system_prompt
    system = build_system_prompt('conversational', client_rules='',
                                 active_tone_profile=PROFILE)
    assert 'ACTIVE TONE PROFILE' in system
    assert 'Warm, direct, unhedged first-person voice.' in system
    assert 'state claims without hedging' in system
    assert 'use corporate jargon' in system  # voice_dont surfaces too


def test_prompt_skips_style_rules_when_profile_active():
    """When both a profile and manual style_rules exist, the profile fully
    replaces the style_rules layer -- that's the precedence Ben chose so the
    Phase 3 delta validation stays clean."""
    from prompts import build_system_prompt
    system = build_system_prompt(
        'conversational',
        client_rules='NEVER USE THE WORD BANANA',
        active_tone_profile=PROFILE,
    )
    assert 'BANANA' not in system, "style_rules must NOT be injected when a Tone Profile is active"
    assert 'CLIENT-SPECIFIC RULES' not in system


def test_prompt_falls_back_to_style_rules_when_no_profile():
    from prompts import build_system_prompt
    system = build_system_prompt(
        'conversational',
        client_rules='NEVER USE THE WORD BANANA',
        active_tone_profile=None,
    )
    assert 'BANANA' in system
    assert 'CLIENT-SPECIFIC RULES' in system


def test_low_score_categories_filtered():
    """Category scoring < 40 shouldn't render at all (no signal, just noise)."""
    from prompts import build_system_prompt
    system = build_system_prompt('conversational', client_rules='', active_tone_profile=PROFILE)
    # humor has score 20 in PROFILE -- should NOT surface.
    assert 'humor' not in system.lower().split('base rules', 1)[0]


def test_low_confidence_categories_marked_as_tendency():
    """Confidence < 40 should render as 'tendency' language, not a rule."""
    from prompts import build_system_prompt
    system = build_system_prompt('conversational', client_rules='', active_tone_profile=PROFILE)
    # joy: score 45 (passes score filter), confidence 30 -- low confidence bucket.
    assert 'low confidence' in system or 'tendency' in system.lower()


def test_review_prompt_also_sees_profile():
    from prompts import build_review_system_prompt
    system = build_review_system_prompt(
        'conversational',
        client_rules='NEVER USE THE WORD BANANA',
        active_tone_profile=PROFILE,
    )
    assert 'ACTIVE TONE PROFILE' in system
    assert 'state claims without hedging' in system
    assert 'BANANA' not in system, "review-pass style_rules must ALSO be skipped when profile active"


def test_no_profile_no_change_to_existing_behavior():
    """Regression guard: nothing should change for clients without a profile."""
    from prompts import build_system_prompt, build_review_system_prompt
    sys1 = build_system_prompt('conversational', client_rules='USE PLAIN LANGUAGE')
    sys2 = build_system_prompt('conversational', client_rules='USE PLAIN LANGUAGE',
                               active_tone_profile=None)
    assert sys1 == sys2
    rev1 = build_review_system_prompt('conversational', client_rules='USE PLAIN LANGUAGE')
    rev2 = build_review_system_prompt('conversational', client_rules='USE PLAIN LANGUAGE',
                                      active_tone_profile=None)
    assert rev1 == rev2


# --- End-to-end route test ---

def test_generate_route_uses_active_profile():
    """When a client has an ACTIVE Tone Profile, /api/generate must inject
    it into the actual prompt sent to Claude, and must NOT inject the
    client's style_rules -- proves the whole chain including the pre-stream
    fetch + stream() closure wiring is correct."""
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_phase2_1.db")
    app_module = _fresh_app(db_path)

    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, 'Harris', 'NEVER USE THE WORD BANANA')")
    raw.execute(
        "INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, "
        "profile_json, status, is_active) VALUES (1, 'default', 1, 'posts', 'x', ?, 'approved', 1)",
        (json.dumps(PROFILE),)
    )
    raw.commit()
    raw.close()

    client = _client(app_module)

    captured = []
    def fake(model, max_tokens, system, messages):
        captured.append(system)
        return "Generated post."

    with patch.object(app_module, "call_anthropic", side_effect=fake):
        r = client.post("/api/generate", json={
            "clientId": 1,
            "transcript": "Post 1:\nWrite about our launch.",
            "style": "conversational",
            "length": "short",
            "format": "plain",
            "tone_context": "default",
        })
        assert r.status_code == 200
        r.get_data()  # force stream() generator to actually run

    joined = '\n'.join(captured)
    assert 'ACTIVE TONE PROFILE' in joined, "profile block never made it into any prompt"
    assert 'state claims without hedging' in joined
    assert 'BANANA' not in joined, "style_rules leaked into prompt even though profile is active"
    os.remove(db_path)


def test_generate_route_falls_back_when_no_active_profile():
    """No active profile => backend behaves exactly like Phase 1: style_rules
    reach the prompt as before. Guarantees clients without a Tone Profile
    aren't silently regressed."""
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_phase2_2.db")
    app_module = _fresh_app(db_path)

    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, 'Harris', 'NEVER USE THE WORD BANANA')")
    raw.commit()
    raw.close()

    client = _client(app_module)
    captured = []
    def fake(model, max_tokens, system, messages):
        captured.append(system)
        return "Generated post."

    with patch.object(app_module, "call_anthropic", side_effect=fake):
        r = client.post("/api/generate", json={
            "clientId": 1,
            "transcript": "Post 1:\nWrite about our launch.",
            "style": "conversational",
            "length": "short",
            "format": "plain",
        })
        assert r.status_code == 200
        r.get_data()

    joined = '\n'.join(captured)
    assert 'BANANA' in joined, "style_rules must still reach the prompt when there's no active profile"
    assert 'ACTIVE TONE PROFILE' not in joined
    os.remove(db_path)


def test_generate_route_respects_tone_context():
    """A profile activated under context='event' must ONLY be picked when
    the request specifies tone_context='event' -- proves the per-context
    routing works."""
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_phase2_3.db")
    app_module = _fresh_app(db_path)

    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, 'Harris', '')")
    event_profile = dict(PROFILE, summary="EVENT VOICE MARKER.")
    raw.execute(
        "INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, "
        "profile_json, status, is_active) VALUES (1, 'event', 1, 'posts', 'x', ?, 'approved', 1)",
        (json.dumps(event_profile),)
    )
    raw.commit()
    raw.close()

    client = _client(app_module)
    captured = []
    def fake(model, max_tokens, system, messages):
        captured.append(system)
        return "Generated post."

    # tone_context defaults to 'default' -- no active profile there, so no marker.
    with patch.object(app_module, "call_anthropic", side_effect=fake):
        client.post("/api/generate", json={
            "clientId": 1, "transcript": "Post 1:\nx", "style": "conversational",
            "length": "short", "format": "plain",
        }).get_data()
    assert 'EVENT VOICE MARKER' not in '\n'.join(captured)

    captured.clear()
    with patch.object(app_module, "call_anthropic", side_effect=fake):
        client.post("/api/generate", json={
            "clientId": 1, "transcript": "Post 1:\nx", "style": "conversational",
            "length": "short", "format": "plain", "tone_context": "event",
        }).get_data()
    assert 'EVENT VOICE MARKER' in '\n'.join(captured), "event-context request did not pick the event profile"
    os.remove(db_path)


if __name__ == "__main__":
    tests = [
        test_prompt_includes_profile_when_active,
        test_prompt_skips_style_rules_when_profile_active,
        test_prompt_falls_back_to_style_rules_when_no_profile,
        test_low_score_categories_filtered,
        test_low_confidence_categories_marked_as_tendency,
        test_review_prompt_also_sees_profile,
        test_no_profile_no_change_to_existing_behavior,
        test_generate_route_uses_active_profile,
        test_generate_route_falls_back_when_no_active_profile,
        test_generate_route_respects_tone_context,
    ]
    for t in tests:
        t()
        print(f"PASS: {t.__name__}")
    print("\nALL TESTS PASSED")
