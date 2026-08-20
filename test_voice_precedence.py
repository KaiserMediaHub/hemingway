"""
Tests for the client-voice precedence fix (2026-08-20, Ben's report: "Harris
Projects is not following the style guides closely").

Root cause: for clients with a real custom voice guide (style_rules and/or
style_docs), the generic STYLE_PROMPTS preset and some absolute BASE_RULES
lines were running in parallel and directly contradicting the client's own
documented voice -- e.g. the "punchy" preset (short, hard-stop sentences)
fought Harris Projects' own rule ("loose... sentences that could verge on
run-on"), and BASE_RULES' "never start with I" fought an intro pattern
Harris's own rules explicitly called for.

Fix: once a client has real client_rules on file, skip the generic preset
entirely and add explicit override language so client rules/examples beat
the two BASE_RULES lines that were found to conflict. Clients with no
client_rules yet still get the preset as a sensible default.

Run with: python -m pytest test_voice_precedence.py -v
(or just: python test_voice_precedence.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prompts import build_system_prompt, build_review_system_prompt, STYLE_PROMPTS


def test_preset_skipped_when_client_has_custom_rules():
    system = build_system_prompt('punchy', 'Use loose, run-on sentences. Never be punchy.')
    assert STYLE_PROMPTS['punchy'] not in system, (
        "the punchy preset text leaked into the prompt even though this client "
        "has their own voice rules on file -- it should be skipped entirely"
    )


def test_preset_used_when_client_has_no_rules_yet():
    system = build_system_prompt('punchy', '')
    assert STYLE_PROMPTS['punchy'] in system, (
        "a client with no custom rules yet should still get the preset as a "
        "sensible default -- this is the onboarding fallback case"
    )


def test_client_rules_override_language_present():
    system = build_system_prompt('thought-leader', 'Some client rule.')
    assert 'take priority over EVERYTHING else' in system
    assert 'the client rule wins' in system


def test_base_rules_carry_explicit_override_clause_for_known_conflicts():
    # These are the two concrete conflicts found in production with Harris
    # Projects: the "never start with I" ban, and the "never both a closer
    # and a question" ban vs. Harris's comment-to-connect CTA examples.
    system = build_system_prompt('thought-leader', 'placeholder')
    assert 'unless the client' in system and 'start with I' not in system  # sanity: rule text intact, just qualified
    assert 'wanted pattern' in system
    assert 'comment-to-connect CTA' in system


def test_review_pass_has_same_precedence_fix():
    system = build_review_system_prompt('punchy', 'Use loose, run-on sentences.')
    assert STYLE_PROMPTS['punchy'] not in system
    assert 'the client rule wins' in system


def test_review_pass_still_uses_preset_for_unconfigured_clients():
    system = build_review_system_prompt('storyteller', '')
    assert STYLE_PROMPTS['storyteller'] in system


if __name__ == '__main__':
    test_preset_skipped_when_client_has_custom_rules()
    print('PASS: test_preset_skipped_when_client_has_custom_rules')
    test_preset_used_when_client_has_no_rules_yet()
    print('PASS: test_preset_used_when_client_has_no_rules_yet')
    test_client_rules_override_language_present()
    print('PASS: test_client_rules_override_language_present')
    test_base_rules_carry_explicit_override_clause_for_known_conflicts()
    print('PASS: test_base_rules_carry_explicit_override_clause_for_known_conflicts')
    test_review_pass_has_same_precedence_fix()
    print('PASS: test_review_pass_has_same_precedence_fix')
    test_review_pass_still_uses_preset_for_unconfigured_clients()
    print('PASS: test_review_pass_still_uses_preset_for_unconfigured_clients')
    print('\nALL TESTS PASSED')
