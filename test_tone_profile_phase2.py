"""
Phase 2 tests (Ben's ask 2026-08-27): active Tone Profile reaches the prompt.
Also proves the /api/generate route uses the active profile end-to-end.

UPDATED 2026-09-10 (precedence v2, Ben's ask): originally an active Tone
Profile fully REPLACED the manual style_rules/reference-copy layer -- that
was so the (now-retired) Delta Analyzer had a clean signal to validate
against. Ben dropped the Delta Analyzer as redundant with edits he already
makes by hand in the Style Rules doc, so the two layers now COMBINE: the
Tone Profile is the voice baseline (typically from a long-form interview),
and the client's own Style Rules are layered on top as higher-trust,
human-reviewed corrections that win on conflict. See build_system_prompt's
"Precedence, v2" comment in prompts.py.

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


def test_prompt_combines_style_rules_with_active_profile():
    """Precedence v2 (2026-09-10): when both a profile and manual style_rules
    exist, BOTH reach the prompt -- the profile as baseline, style_rules as
    higher-trust explicit corrections layered on top. Both markers must be
    present, and the client-rules text should be framed as taking priority
    over the profile on conflict."""
    from prompts import build_system_prompt
    system = build_system_prompt(
        'conversational',
        client_rules='NEVER USE THE WORD BANANA',
        active_tone_profile=PROFILE,
    )
    assert 'ACTIVE TONE PROFILE' in system
    assert 'BANANA' in system, "style_rules must still reach the prompt alongside an active Tone Profile"
    assert 'CLIENT-SPECIFIC RULES' in system
    assert 'take priority over the Tone Profile above' in system


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


def test_review_prompt_also_sees_profile_and_style_rules():
    from prompts import build_review_system_prompt
    system = build_review_system_prompt(
        'conversational',
        client_rules='NEVER USE THE WORD BANANA',
        active_tone_profile=PROFILE,
    )
    assert 'ACTIVE TONE PROFILE' in system
    assert 'state claims without hedging' in system
    assert 'BANANA' in system, "review-pass style_rules must combine with an active profile, not be skipped"


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


def test_write_post_for_section_includes_reference_copy_with_active_profile():
    """Precedence v2 (2026-09-10): reference copy (uploaded sample docs) and
    client_rules must reach the actual USER prompt even when a Tone Profile
    is active -- the old suppression in write_post_for_section existed only
    to keep a clean signal for the now-retired Delta Analyzer.

    Uses _fresh_app (temp DB_PATH) like every other app-touching test in this
    file, rather than a bare `import app` -- importing app.py runs init_db()
    at import time against whatever DB_PATH is currently set, and this file
    must never let that fall through to the real local/production database."""
    db_path = os.path.join(tempfile.gettempdir(), "hemingway_test_phase2_4.db")
    app_module = _fresh_app(db_path)
    captured_user = []

    def fake(model, max_tokens, system, messages):
        captured_user.append(messages[0]['content'])
        return "Generated post."

    with patch.object(app_module, "call_anthropic", side_effect=fake):
        app_module.write_post_for_section(
            'Title', 'Section body text.', 'Full corpus text.',
            'conversational', 'short', 'NEVER USE THE WORD BANANA',
            'REAL REFERENCE COPY MARKER', '', {},
            active_tone_profile=PROFILE,
        )
    joined = '\n'.join(captured_user)
    assert 'REAL REFERENCE COPY MARKER' in joined, (
        "reference copy must reach the user prompt alongside an active Tone Profile"
    )
    os.remove(db_path)


# --- End-to-end route test ---

def test_generate_route_uses_active_profile():
    """When a client has an ACTIVE Tone Profile, /api/generate must inject
    it into the actual prompt sent to Claude, AND (precedence v2) must still
    inject the client's style_rules alongside it -- proves the whole chain
    including the pre-stream fetch + stream() closure wiring is correct."""
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
    assert 'BANANA' in joined, "style_rules must combine with an active profile (precedence v2), not be suppressed"
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
        test_prompt_combines_style_rules_with_active_profile,
        test_prompt_falls_back_to_style_rules_when_no_profile,
        test_low_score_categories_filtered,
        test_low_confidence_categories_marked_as_tendency,
        test_review_prompt_also_sees_profile_and_style_rules,
        test_write_post_for_section_includes_reference_copy_with_active_profile,
        test_no_profile_no_change_to_existing_behavior,
        test_generate_route_uses_active_profile,
        test_generate_route_falls_back_when_no_active_profile,
        test_generate_route_respects_tone_context,
    ]
    for t in tests:
        t()
        print(f"PASS: {t.__name__}")
    print("\nALL TESTS PASSED")
