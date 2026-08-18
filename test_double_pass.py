"""
Tests for the double-pass style/voice QA check added 2026-08-18 (Ben's ask:
"make sure Hemingway is following the style and voice guide"). Every post now
goes through write_post_for_section(), which does a first drafting pass and
then a second, independent review pass that checks the draft against the same
style/voice standards and silently revises it if anything slipped through.

Run with: python -m pytest test_double_pass.py -v
(or just: python test_double_pass.py)
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as hemingway_app


def test_write_post_makes_two_calls_and_returns_revised_text():
    calls = []

    def fake_call_anthropic(model, max_tokens, system, messages):
        calls.append({'system': system, 'user': messages[0]['content']})
        if len(calls) == 1:
            return "In today's fast-paced world, we leverage synergy."
        return "Here is the actual point, cleaned up."

    with patch.object(hemingway_app, 'call_anthropic', side_effect=fake_call_anthropic):
        result = hemingway_app.write_post_for_section(
            'Test Video', 'section body text', 'full corpus text',
            'thought-leader', 'short', 'Always mention ROI.',
            'sample style doc text', 'launch context'
        )

    assert len(calls) == 2, f"expected 2 Anthropic calls (draft + review), got {len(calls)}"
    assert result == "Here is the actual point, cleaned up."
    # Review pass must carry forward the same standards the draft was written against
    assert 'meticulous style and voice editor' in calls[1]['system']
    assert 'Always mention ROI.' in calls[1]['system']
    # Review pass must actually receive the draft to check, not write from scratch
    assert "In today's fast-paced world" in calls[1]['user']


def test_review_failure_falls_back_to_draft():
    call_count = [0]

    def flaky_call_anthropic(model, max_tokens, system, messages):
        call_count[0] += 1
        if call_count[0] == 1:
            return 'GOOD DRAFT TEXT'
        raise Exception('Simulated API failure on review pass')

    with patch.object(hemingway_app, 'call_anthropic', side_effect=flaky_call_anthropic):
        result = hemingway_app.write_post_for_section(
            'Test', 'body', 'corpus', 'punchy', 'short', '', '', ''
        )

    assert result == 'GOOD DRAFT TEXT', (
        "if the review pass errors, the working draft must still be returned -- "
        "a post that skipped QA beats no post at all"
    )


def test_review_pass_used_by_regenerate_route_too():
    # rewrite_post() (the "Regenerate" button in Studio/Hemingway) calls the
    # exact same write_post_for_section() helper, so it gets the same
    # double-pass coverage for free -- this just documents/locks that in.
    import inspect
    source = inspect.getsource(hemingway_app.rewrite_post)
    assert 'write_post_for_section(' in source


if __name__ == '__main__':
    test_write_post_makes_two_calls_and_returns_revised_text()
    print('PASS: test_write_post_makes_two_calls_and_returns_revised_text')
    test_review_failure_falls_back_to_draft()
    print('PASS: test_review_failure_falls_back_to_draft')
    test_review_pass_used_by_regenerate_route_too()
    print('PASS: test_review_pass_used_by_regenerate_route_too')
    print('\nALL TESTS PASSED')
