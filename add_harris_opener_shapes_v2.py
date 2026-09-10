"""
One-off script (Ben's ask, 2026-09-09): "Ok, now write the code and
instructions so we can push an update and test."

Builds Harris Projects' Phase 5 Tone Profile update as a new PENDING version
-- NOT another live in-place edit like the earlier em-dash fix. This is the
deliberate choice Ben asked for: he reviews and activates it himself in
Style & Voice, same as any other proposed version.

What this adds, layered on top of whatever's currently active for Harris'
'default' context:
  - opener_shapes: the 25 reusable structural shapes Ben and Claude worked
    through together (5 buckets: declarative fact, topic-plus-twist,
    reflective/evocative hook, narrative, scene-setting/conditions).
    Ben cut a 26th shape (a competitor-comparison opener) -- Harris dislikes
    comparison framing.
  - voice_do / voice_dont: merged (deduped) with the consolidated rules from
    the 12 before/after post pairs + Tim's explicit style-preference list.
    The "no em-dashes" rule is already live from an earlier direct edit --
    this script re-asserts it defensively in case it's missing.

Does NOT touch: summary, scored categories (directness/concreteness/etc.),
example_posts, target_length, rejection_list, source_mix -- those carry
forward unchanged from the parent version.

Run ONCE on the server:
    cd /var/www/hemingway
    venv/bin/python3 add_harris_opener_shapes_v2.py   (or: python3 ... if no venv)

Safe to re-run: it always creates a NEW pending version (never edits in
place), so re-running just adds another pending version on top -- check
Style & Voice -> Versions first if you're not sure whether it already ran.
"""

import json
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'hemingway.db')

CONTEXT = 'default'

OPENER_SHAPES = [
    # Declarative fact
    "On this [job type], we [specific action].",
    "We just wrapped up [certification/milestone], which means [what it enables].",
    "This [job type] involved [specific technical decision].",
    "We spent [timeframe] on [specific task] for this [job type].",
    "On this build, [detail] came down to [decision/tradeoff].",
    # Topic-plus-twist
    "[Material/technique] does X on its own, but we [went further].",
    "[Thing] sounds simple. It isn't.",
    "[Standard approach] was the obvious choice here, but we went with [alternative] instead.",
    "This isn't just [surface description]. It's [deeper reason].",
    "[Detail] is the kind of thing most people never think about, until [consequence].",
    # Reflective / evocative hook
    "There's a reason [detail] never shows up in photos.",
    "Not every upgrade is visible, but [this one] matters more than most.",
    "It's easy to miss what's actually [holding/protecting/supporting] [X].",
    "Some [decisions/details] on a job site are bigger than they look.",
    "You don't always notice good work. You notice when it's missing.",
    "A few [changes] made a bigger difference here than you'd expect.",
    "This is the kind of detail that separates good from great.",
    # Narrative
    "We got called out for [reason], and found [more than expected].",
    "This started as [small thing] and turned into [bigger thing].",
    "We were brought in to [fix one thing] and ended up [doing more].",
    "This owner gave us [X options], and the choice wasn't as obvious as it sounds.",
    "A [walkthrough/morning on site] turned into [bigger project].",
    # Scene-setting / conditions
    "Between [condition A], [condition B], and [condition C], homes on the Gulf Coast deal with [ongoing challenge].",
    "[Environmental factor] is something every Gulf Coast [home/build] has to deal with.",
    "[Conditions] take a toll on [material/system] if it isn't done right.",
]

NEW_VOICE_DO = [
    "Combine short factual details into one flowing sentence instead of choppy fragments.",
    "When describing a finished change, state the concrete result/feeling, not just that work happened.",
    "Use \"we\", not \"I\".",
    "Translate trade jargon into plain physical language.",
    "Use numerals for measurements, never spelled out.",
    "When a post rides with a video, summarize briefly and let the video carry technical detail.",
    "Drop in one short, confident sentence occasionally as a deliberate values/why beat.",
    "Rotate opener style rather than repeating the same structure.",
]

NEW_VOICE_DONT = [
    "Em-dashes anywhere, no exceptions.",
    "Trade jargon left untranslated (e.g. shear capacity, thermal barrier, building envelope, diaphragm, \"transitions between materials\").",
    "Framing that implies criticism of a prior contractor or the property's past condition.",
    "Hype words or absolute claims (\"100%\", \"guaranteed\", \"never\", \"always\", \"locked in\").",
    "Switching from first-person \"we\" into third-person company references mid-post -- a CTA must stay in the same voice as the rest of the post.",
    "A forced hard-sell CTA -- it's optional, and skipping it is fine.",
]


def _merge_dedup(existing, additions):
    existing = list(existing or [])
    seen = {e.strip().lower() for e in existing}
    for item in additions:
        if item.strip().lower() not in seen:
            existing.append(item)
            seen.add(item.strip().lower())
    return existing


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    client_row = conn.execute("SELECT id FROM clients WHERE name LIKE '%Harris%'").fetchone()
    if not client_row:
        print("No client matching '%Harris%' found -- aborting, nothing changed.")
        return
    client_id = client_row['id']

    active = conn.execute(
        "SELECT * FROM tone_profiles WHERE client_id = ? AND context = ? AND is_active = 1",
        (client_id, CONTEXT)
    ).fetchone()
    if not active:
        print(f"No active Tone Profile for Harris/{CONTEXT} -- aborting. "
              "Generate and activate a v1 profile first (Style & Voice tab).")
        return

    profile = json.loads(active['profile_json'])

    profile['opener_shapes'] = OPENER_SHAPES
    profile['voice_do'] = _merge_dedup(profile.get('voice_do'), NEW_VOICE_DO)
    profile['voice_dont'] = _merge_dedup(profile.get('voice_dont'), NEW_VOICE_DONT)

    max_version_row = conn.execute(
        "SELECT MAX(version) AS v FROM tone_profiles WHERE client_id = ? AND context = ?",
        (client_id, CONTEXT)
    ).fetchone()
    new_version = (max_version_row['v'] or 0) + 1

    change_summary = (
        "Phase 5 (2026-09-09): added 25 reusable opener shapes across 5 pattern "
        "buckets (declarative fact, topic-plus-twist, reflective/evocative hook, "
        "narrative, scene-setting/conditions), derived from a 12-pair before/after "
        "voice analysis plus Tim's explicit style-preference list. Also merged in "
        "the consolidated always-do/never-do rules from that same analysis "
        "(combine short details into flowing sentences, translate jargon, numerals "
        "for measurements, no em-dashes, no hype words, no third-person CTA "
        "switches, optional CTAs, etc). Pending -- review and activate in Style & Voice."
    )

    conn.execute(
        "INSERT INTO tone_profiles "
        "(client_id, context, version, source_type, source_text, profile_json, "
        "rejection_list, source_mix, change_summary, parent_version, status, is_active, "
        "example_posts, target_length, rejection_reason) "
        "VALUES (?, ?, ?, 'manual', ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, '')",
        (
            client_id, CONTEXT, new_version,
            'Opener shapes + consolidated voice rules, assembled manually from a 12-pair '
            'before/after analysis and Tim\'s explicit style list (see 2026-09-09 conversation).',
            json.dumps(profile),
            active['rejection_list'],
            active['source_mix'],
            change_summary,
            active['version'],
            active['example_posts'],
            active['target_length'],
        )
    )
    conn.commit()
    conn.close()

    print(f"Created v{new_version} for client_id={client_id}, context={CONTEXT}, status=pending.")
    print(f"Parent version: v{active['version']}.")
    print("Nothing was activated. Go to Hemingway -> Harris Projects -> Style & Voice -> "
          f"Versions and review/activate v{new_version} yourself.")


if __name__ == '__main__':
    main()
