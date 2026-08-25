"""
Tests for plain-text post input (Ben's ask, 2026-08-24): "I want to be able
to type in posts I want it to write without all the timestamps details."
Adds a second input format alongside the existing Degas-transcript format --
"Post 1: ...", "Post 2: ..." blocks, no VIDEO headers or timestamps needed.

Run with: python -m pytest test_plain_text_input.py -v
(or just: python test_plain_text_input.py)
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prompts import split_transcript_plain


def test_basic_two_posts():
    text = (
        "Post 1:\n"
        "This is a post that I want you to write.\n\n"
        "Post 2:\n"
        "This is another post I want you to write."
    )
    sections = split_transcript_plain(text)
    assert len(sections) == 2
    assert sections[0] == {'title': 'Post 1', 'body': 'This is a post that I want you to write.'}
    assert sections[1] == {'title': 'Post 2', 'body': 'This is another post I want you to write.'}


def test_inline_content_on_same_line_as_header():
    text = "Post 1: Do the thing right now.\nPost 2: Then do this other thing."
    sections = split_transcript_plain(text)
    assert sections[0]['body'] == 'Do the thing right now.'
    assert sections[1]['body'] == 'Then do this other thing.'


def test_multi_line_body_per_post():
    text = (
        "Post 1:\n"
        "First sentence.\n"
        "Second sentence on its own line.\n\n"
        "Post 2:\n"
        "Only one line here."
    )
    sections = split_transcript_plain(text)
    assert sections[0]['body'] == 'First sentence. Second sentence on its own line.'
    assert sections[1]['body'] == 'Only one line here.'


def test_case_insensitive_and_no_posts_returns_empty():
    text = "post 1:\nlowercase works too."
    sections = split_transcript_plain(text)
    assert len(sections) == 1
    assert sections[0]['title'] == 'Post 1'

    assert split_transcript_plain("just some random text with no Post markers") == []


def test_generate_route_uses_plain_parser_when_format_is_plain():
    os.environ.setdefault("SECRET_KEY", "test")
    os.environ.setdefault("APP_PASSWORD", "test")
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
    os.environ.setdefault("DB_PATH", "/tmp/hemingway_test_plain_format.db")
    if os.path.exists("/tmp/hemingway_test_plain_format.db"):
        os.remove("/tmp/hemingway_test_plain_format.db")

    import app as hemingway_app
    import db as hemingway_db
    hemingway_db.DB_PATH = "/tmp/hemingway_test_plain_format.db"
    hemingway_app.DB_PATH = "/tmp/hemingway_test_plain_format.db"
    hemingway_db.init_db()

    conn = hemingway_db.get_db.__wrapped__ if hasattr(hemingway_db.get_db, "__wrapped__") else None
    import sqlite3
    raw = sqlite3.connect("/tmp/hemingway_test_plain_format.db")
    raw.execute("INSERT INTO clients (id, name, style_rules) VALUES (1, 'Test Co', '')")
    raw.commit()
    raw.close()

    client = hemingway_app.app.test_client()
    with client.session_transaction() as sess:
        sess["logged_in"] = True

    def fake_call_anthropic(model, max_tokens, system, messages):
        return "Generated post text."

    with patch.object(hemingway_app, "call_anthropic", side_effect=fake_call_anthropic):
        resp = client.post("/api/generate", json={
            "clientId": 1,
            "transcript": "Post 1:\nWrite about our new launch.",
            "style": "conversational",
            "length": "short",
            "format": "plain",
        })
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert '"type": "start"' in body or '"type":"start"' in body.replace(' ', '')
        assert '"total": 1' in body or '"total":1' in body.replace(' ', '')

    os.remove("/tmp/hemingway_test_plain_format.db")


if __name__ == '__main__':
    test_basic_two_posts()
    print('PASS: test_basic_two_posts')
    test_inline_content_on_same_line_as_header()
    print('PASS: test_inline_content_on_same_line_as_header')
    test_multi_line_body_per_post()
    print('PASS: test_multi_line_body_per_post')
    test_case_insensitive_and_no_posts_returns_empty()
    print('PASS: test_case_insensitive_and_no_posts_returns_empty')
    test_generate_route_uses_plain_parser_when_format_is_plain()
    print('PASS: test_generate_route_uses_plain_parser_when_format_is_plain')
    print('\nALL TESTS PASSED')
