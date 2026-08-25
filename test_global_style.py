"""
Tests for editable Global Style (Ben's ask, 2026-08-24: "is there a spot
where I can edit the global style? Things that every client needs"). Was
hardcoded in prompts.py (GLOBAL_STYLE_DOC/BASE_RULES), now lives in the
global_style table, editable from a "Global Style" button in the header, and
seeded from the same defaults on first init.

Run with: python -m pytest test_global_style.py -v
(or just: python test_global_style.py)
"""

import os
import sys
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
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    return client


def test_global_style_seeded_from_defaults_on_first_init():
    from prompts import DEFAULT_GLOBAL_STYLE_DOC, DEFAULT_BASE_RULES
    app_module = _fresh_app("/tmp/hemingway_test_global_style_1.db")
    client = _client(app_module)
    resp = client.get("/api/global-style")
    data = resp.get_json()
    assert data["global_style_doc"] == DEFAULT_GLOBAL_STYLE_DOC
    assert data["base_rules"] == DEFAULT_BASE_RULES
    os.remove("/tmp/hemingway_test_global_style_1.db")


def test_update_and_read_back():
    app_module = _fresh_app("/tmp/hemingway_test_global_style_2.db")
    client = _client(app_module)
    resp = client.put("/api/global-style", json={
        "global_style_doc": "Custom tone rules.",
        "base_rules": "Custom hard rules.",
    })
    assert resp.status_code == 200
    resp2 = client.get("/api/global-style")
    data = resp2.get_json()
    assert data["global_style_doc"] == "Custom tone rules."
    assert data["base_rules"] == "Custom hard rules."
    os.remove("/tmp/hemingway_test_global_style_2.db")


def test_rejects_empty_fields():
    app_module = _fresh_app("/tmp/hemingway_test_global_style_3.db")
    client = _client(app_module)
    resp = client.put("/api/global-style", json={"global_style_doc": "", "base_rules": "still here"})
    assert resp.status_code == 400
    os.remove("/tmp/hemingway_test_global_style_3.db")


def test_reset_defaults_endpoint_returns_originals_without_saving():
    from prompts import DEFAULT_GLOBAL_STYLE_DOC, DEFAULT_BASE_RULES
    app_module = _fresh_app("/tmp/hemingway_test_global_style_4.db")
    client = _client(app_module)
    client.put("/api/global-style", json={"global_style_doc": "changed", "base_rules": "changed"})

    resp = client.get("/api/global-style/reset-defaults")
    data = resp.get_json()
    assert data["global_style_doc"] == DEFAULT_GLOBAL_STYLE_DOC
    assert data["base_rules"] == DEFAULT_BASE_RULES

    # reset-defaults must NOT have actually saved anything -- it's a value
    # the frontend puts in the textareas, not applied until Save is clicked.
    still_changed = client.get("/api/global-style").get_json()
    assert still_changed["global_style_doc"] == "changed"
    os.remove("/tmp/hemingway_test_global_style_4.db")


def test_generate_route_actually_uses_saved_global_style():
    app_module = _fresh_app("/tmp/hemingway_test_global_style_5.db")
    client = _client(app_module)
    client.put("/api/global-style", json={
        "global_style_doc": "UNIQUE_MARKER_TONE_RULES",
        "base_rules": "UNIQUE_MARKER_HARD_RULES",
    })

    import sqlite3
    raw = sqlite3.connect("/tmp/hemingway_test_global_style_5.db")
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, 'Test Co', '')")
    raw.commit()
    raw.close()

    captured_systems = []

    def fake_call_anthropic(model, max_tokens, system, messages):
        captured_systems.append(system)
        return "Generated post."

    with patch.object(app_module, "call_anthropic", side_effect=fake_call_anthropic):
        resp = client.post("/api/generate", json={
            "clientId": 1,
            "transcript": "Post 1:\nWrite about our launch.",
            "style": "conversational",
            "length": "short",
            "format": "plain",
        })
        assert resp.status_code == 200
        resp.get_data()  # streamed response -- forces the generator to actually run

    assert any("UNIQUE_MARKER_TONE_RULES" in s for s in captured_systems), (
        "the saved global_style_doc never reached the actual prompt sent to Claude"
    )
    assert any("UNIQUE_MARKER_HARD_RULES" in s for s in captured_systems), (
        "the saved base_rules never reached the actual prompt sent to Claude"
    )
    os.remove("/tmp/hemingway_test_global_style_5.db")


if __name__ == '__main__':
    test_global_style_seeded_from_defaults_on_first_init()
    print('PASS: test_global_style_seeded_from_defaults_on_first_init')
    test_update_and_read_back()
    print('PASS: test_update_and_read_back')
    test_rejects_empty_fields()
    print('PASS: test_rejects_empty_fields')
    test_reset_defaults_endpoint_returns_originals_without_saving()
    print('PASS: test_reset_defaults_endpoint_returns_originals_without_saving')
    test_generate_route_actually_uses_saved_global_style()
    print('PASS: test_generate_route_actually_uses_saved_global_style')
    print('\nALL TESTS PASSED')
