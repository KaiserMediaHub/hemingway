import os
import json
import random
import sqlite3
from functools import wraps
from flask import Flask, request, session, jsonify, send_from_directory, Response, stream_with_context
from dotenv import load_dotenv
import anthropic as anthropic_sdk
from db import init_db, get_db, close_db, DB_PATH
from prompts import (
    build_system_prompt, build_user_prompt, split_transcript, split_transcript_plain,
    build_review_system_prompt, build_review_user_prompt,
    build_tone_profile_prompt, build_tone_profile_change_summary_prompt,
    build_delta_analysis_prompt, build_delta_regenerate_user_prompt,
    TONE_PROFILE_CATEGORIES,
)

load_dotenv()

app = Flask(__name__, static_folder='public', static_url_path='')
app.secret_key = os.environ.get('SESSION_SECRET', 'hemingway-kmg-secret-change-this')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 30 * 24 * 60 * 60  # 30 days

PORT = int(os.environ.get('PORT', 3000))
TEAM_PASSWORD = os.environ.get('TEAM_PASSWORD', 'changeme')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

app.teardown_appcontext(close_db)

with app.app_context():
    init_db()


# ---------- Auth ----------

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': {'message': 'Not authenticated'}}), 401
        return f(*args, **kwargs)
    return decorated


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    if data and data.get('password') == TEAM_PASSWORD:
        session.permanent = True
        session['logged_in'] = True
        return jsonify({'ok': True})
    return jsonify({'error': {'message': 'Incorrect password'}}), 401


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})


@app.route('/api/session')
def check_session():
    return jsonify({'loggedIn': bool(session.get('logged_in'))})


# ---------- Clients ----------

@app.route('/api/clients', methods=['GET'])
@require_auth
def get_clients():
    db = get_db()
    rows = db.execute('SELECT id, name, style_rules, created_at FROM clients ORDER BY name ASC').fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/clients', methods=['POST'])
@require_auth
def create_client():
    data = request.get_json()
    name = (data.get('name') or '').strip() if data else ''
    if not name:
        return jsonify({'error': {'message': 'Name is required.'}}), 400
    db = get_db()
    cursor = db.execute('INSERT INTO clients (name) VALUES (?)', (name,))
    db.commit()
    row = db.execute('SELECT id, name, style_rules, created_at FROM clients WHERE id = ?', (cursor.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.route('/api/clients/<int:client_id>', methods=['GET'])
@require_auth
def get_client(client_id):
    db = get_db()
    row = db.execute('SELECT id, name, style_rules, created_at FROM clients WHERE id = ?', (client_id,)).fetchone()
    if not row:
        return jsonify({'error': {'message': 'Client not found.'}}), 404
    return jsonify(dict(row))


@app.route('/api/clients/<int:client_id>', methods=['PUT'])
@require_auth
def update_client(client_id):
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    style_rules = data.get('styleRules', '')
    if not name:
        return jsonify({'error': {'message': 'Name is required.'}}), 400
    db = get_db()
    if not db.execute('SELECT id FROM clients WHERE id = ?', (client_id,)).fetchone():
        return jsonify({'error': {'message': 'Client not found.'}}), 404
    db.execute('UPDATE clients SET name = ?, style_rules = ? WHERE id = ?', (name, style_rules, client_id))
    db.commit()
    row = db.execute('SELECT id, name, style_rules, created_at FROM clients WHERE id = ?', (client_id,)).fetchone()
    return jsonify(dict(row))


@app.route('/api/clients/<int:client_id>/style-rules', methods=['PUT'])
@require_auth
def update_style_rules(client_id):
    data = request.get_json() or {}
    style_rules = data.get('style_rules', data.get('styleRules', ''))
    db = get_db()
    if not db.execute('SELECT id FROM clients WHERE id = ?', (client_id,)).fetchone():
        return jsonify({'error': {'message': 'Client not found.'}}), 404
    db.execute('UPDATE clients SET style_rules = ? WHERE id = ?', (style_rules, client_id))
    db.commit()
    return jsonify({'ok': True})


@app.route('/api/clients/<int:client_id>', methods=['DELETE'])
@require_auth
def delete_client(client_id):
    db = get_db()
    db.execute('DELETE FROM clients WHERE id = ?', (client_id,))
    db.commit()
    return jsonify({'ok': True})


# ---------- Global Style ----------
# Rules that apply to every client, regardless of their own style_rules
# (Ben's ask, 2026-08-24). Single row in global_style, seeded from
# prompts.DEFAULT_GLOBAL_STYLE_DOC/DEFAULT_BASE_RULES the first time the
# table is empty -- see db.py's init_db().

def get_global_style():
    db = get_db()
    row = db.execute('SELECT global_style_doc, base_rules FROM global_style WHERE id = 1').fetchone()
    if not row:
        # Shouldn't happen -- init_db() seeds this row -- but fall back to
        # the hardcoded defaults rather than crashing if it somehow is missing.
        from prompts import DEFAULT_GLOBAL_STYLE_DOC, DEFAULT_BASE_RULES
        return {'global_style_doc': DEFAULT_GLOBAL_STYLE_DOC, 'base_rules': DEFAULT_BASE_RULES}
    return dict(row)


@app.route('/api/global-style', methods=['GET'])
@require_auth
def get_global_style_route():
    return jsonify(get_global_style())


@app.route('/api/global-style', methods=['PUT'])
@require_auth
def update_global_style():
    data = request.get_json() or {}
    global_style_doc = data.get('global_style_doc', '').strip()
    base_rules = data.get('base_rules', '').strip()
    if not global_style_doc or not base_rules:
        return jsonify({'error': {'message': 'Both fields are required -- clear the text and use "Reset to default" instead of saving empty.'}}), 400
    db = get_db()
    db.execute(
        'UPDATE global_style SET global_style_doc = ?, base_rules = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1',
        (global_style_doc, base_rules)
    )
    db.commit()
    return jsonify(get_global_style())


@app.route('/api/global-style/reset-defaults', methods=['GET'])
@require_auth
def get_global_style_defaults():
    """Lets the UI offer a 'reset to default' action without hardcoding the
    default text twice (once in prompts.py, once in the frontend)."""
    from prompts import DEFAULT_GLOBAL_STYLE_DOC, DEFAULT_BASE_RULES
    return jsonify({'global_style_doc': DEFAULT_GLOBAL_STYLE_DOC, 'base_rules': DEFAULT_BASE_RULES})


# ---------- Tone Profile (Phase 1: generate + version + activate, INERT) ----------
# Ben's ask 2026-08-27: a versioned Tone Profile per client per context that
# evolves over time. Phase 1 stores profiles; Phase 2 wires them into
# generation; Phase 3 adds the Delta Analyzer. See prompts.py for the
# category list and prompt construction.

def _count_written_chars(source_type, source_text):
    """Track a rough spoken/written source mix so future versions can weight
    trust accordingly. Cheap heuristic -- just categorize by source_type."""
    n = len(source_text or '')
    if source_type == 'transcript':
        return {'spoken_chars': n, 'written_chars': 0}
    return {'spoken_chars': 0, 'written_chars': n}


def _merge_source_mix(parent_mix_json, added_mix):
    parent = json.loads(parent_mix_json) if parent_mix_json else {}
    return {
        'spoken_chars': parent.get('spoken_chars', 0) + added_mix.get('spoken_chars', 0),
        'written_chars': parent.get('written_chars', 0) + added_mix.get('written_chars', 0),
    }


def _merge_example_posts(existing_json, new_text, cap=3):
    """Accumulate up to `cap` verbatim client-voice examples (Ben's ask,
    2026-09-08: raw examples are higher signal than the scored category
    breakdown). Keeps the MOST RECENT `cap` entries -- newer client edits are
    presumably still-current voice, so a full list drops the oldest first."""
    try:
        existing = json.loads(existing_json) if existing_json else []
    except (TypeError, ValueError):
        existing = []
    if not isinstance(existing, list):
        existing = []
    text = (new_text or '').strip()
    if text and text not in existing:
        existing.append(text)
    return json.dumps(existing[-cap:], ensure_ascii=False)


def _compute_target_length(example_posts_json):
    """Word-count stats derived from example_posts -- Ben's ask, 2026-09-08:
    Hemingway has been running long compared to real client output, and
    length is cheap, concrete signal the category system doesn't capture."""
    try:
        posts = json.loads(example_posts_json) if example_posts_json else []
    except (TypeError, ValueError):
        posts = []
    counts = [len(p.split()) for p in posts if isinstance(p, str) and p.strip()]
    if not counts:
        return '{}'
    return json.dumps({
        'avg_words': sum(counts) // len(counts),
        'min_words': min(counts),
        'max_words': max(counts),
    })


@app.route('/api/clients/<int:client_id>/tone-profiles', methods=['GET'])
@require_auth
def list_tone_profiles(client_id):
    """List every version for this client, optionally filtered by context.
    Ordered newest-first so the UI can show current + history at a glance."""
    context = request.args.get('context')
    db = get_db()
    if context:
        rows = db.execute(
            'SELECT id, client_id, context, version, source_type, profile_json, change_summary, '
            'parent_version, status, is_active, source_mix, created_at, example_posts, target_length, '
            'rejection_reason '
            'FROM tone_profiles WHERE client_id = ? AND context = ? ORDER BY version DESC',
            (client_id, context)
        ).fetchall()
    else:
        rows = db.execute(
            'SELECT id, client_id, context, version, source_type, profile_json, change_summary, '
            'parent_version, status, is_active, source_mix, created_at, example_posts, target_length, '
            'rejection_reason '
            'FROM tone_profiles WHERE client_id = ? ORDER BY context, version DESC',
            (client_id,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/clients/<int:client_id>/tone-profiles/active', methods=['GET'])
@require_auth
def get_active_tone_profile(client_id):
    """Return the currently active profile for a given context (defaults to
    'default'), or null if none exists yet."""
    context = request.args.get('context', 'default')
    db = get_db()
    row = db.execute(
        'SELECT * FROM tone_profiles WHERE client_id = ? AND context = ? AND is_active = 1',
        (client_id, context)
    ).fetchone()
    return jsonify(dict(row) if row else None)


@app.route('/api/clients/<int:client_id>/tone-profiles', methods=['POST'])
@require_auth
def create_tone_profile(client_id):
    """Generate a new Tone Profile version from pasted source material.
    Status defaults to 'pending' -- Ben must explicitly activate before it
    affects anything (though Phase 1 doesn't wire it into generation yet)."""
    data = request.get_json() or {}
    source_type = (data.get('source_type') or '').strip().lower()
    source_text = (data.get('source_text') or '').strip()
    context = (data.get('context') or 'default').strip() or 'default'

    if source_type not in ('transcript', 'posts'):
        return jsonify({'error': {'message': "source_type must be 'transcript' or 'posts'."}}), 400
    if len(source_text) < 200:
        return jsonify({'error': {'message': 'Source text is too short to derive a meaningful profile (min 200 chars).'}}), 400

    db = get_db()
    if not db.execute('SELECT id FROM clients WHERE id = ?', (client_id,)).fetchone():
        return jsonify({'error': {'message': 'Client not found.'}}), 404

    # Find the current highest version for this (client, context) so we can
    # increment. First-ever profile for this context starts at v1.
    latest = db.execute(
        'SELECT version, source_mix, profile_json FROM tone_profiles '
        'WHERE client_id = ? AND context = ? ORDER BY version DESC LIMIT 1',
        (client_id, context)
    ).fetchone()
    next_version = (latest['version'] + 1) if latest else 1
    parent_version = latest['version'] if latest else None

    # Generate the profile JSON via Claude.
    system, user = build_tone_profile_prompt(source_type, source_text, context=context)
    try:
        raw = call_anthropic(
            model='claude-sonnet-4-5',
            max_tokens=4000,
            system=system,
            messages=[{'role': 'user', 'content': user}]
        )
    except Exception as e:
        return jsonify({'error': {'message': f'Profile generation failed: {e}'}}), 502

    # Defensive JSON extraction -- the prompt asks for pure JSON but strip any
    # accidental fences just in case the model wraps it.
    cleaned = raw.strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.strip('`')
        if cleaned.lower().startswith('json'):
            cleaned = cleaned[4:].strip()
    try:
        profile_obj = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return jsonify({'error': {'message': f'Model returned invalid JSON: {e}. Raw start: {cleaned[:200]}'}}), 502

    profile_json_str = json.dumps(profile_obj, ensure_ascii=False)

    # Change summary vs parent (skipped for v1 -- no parent).
    change_summary = ''
    if latest:
        try:
            sys2, usr2 = build_tone_profile_change_summary_prompt(latest['profile_json'], profile_json_str)
            change_summary = call_anthropic(
                model='claude-sonnet-4-5', max_tokens=400, system=sys2,
                messages=[{'role': 'user', 'content': usr2}]
            ).strip()
        except Exception:
            change_summary = '(change summary unavailable)'

    added_mix = _count_written_chars(source_type, source_text)
    source_mix = _merge_source_mix(latest['source_mix'] if latest else None, added_mix)

    cur = db.execute(
        'INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, '
        'profile_json, rejection_list, source_mix, change_summary, parent_version, status, is_active) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (client_id, context, next_version, source_type, source_text, profile_json_str,
         '[]', json.dumps(source_mix), change_summary, parent_version, 'pending', 0)
    )
    db.commit()
    new_id = cur.lastrowid
    row = db.execute('SELECT * FROM tone_profiles WHERE id = ?', (new_id,)).fetchone()
    return jsonify(dict(row))


@app.route('/api/clients/<int:client_id>/tone-profiles/<int:profile_id>/activate', methods=['POST'])
@require_auth
def activate_tone_profile(client_id, profile_id):
    """Mark a profile as approved + active. Only ONE profile per
    (client, context) may be active at a time -- old actives get flipped
    off, not deleted (revert is a matter of activating an older version)."""
    db = get_db()
    row = db.execute(
        'SELECT * FROM tone_profiles WHERE id = ? AND client_id = ?',
        (profile_id, client_id)
    ).fetchone()
    if not row:
        return jsonify({'error': {'message': 'Profile not found for this client.'}}), 404
    db.execute(
        'UPDATE tone_profiles SET is_active = 0 WHERE client_id = ? AND context = ? AND id != ?',
        (client_id, row['context'], profile_id)
    )
    db.execute(
        "UPDATE tone_profiles SET is_active = 1, status = 'approved' WHERE id = ?",
        (profile_id,)
    )
    db.commit()
    updated = db.execute('SELECT * FROM tone_profiles WHERE id = ?', (profile_id,)).fetchone()
    return jsonify(dict(updated))


@app.route('/api/clients/<int:client_id>/tone-profiles/<int:profile_id>/reject', methods=['POST'])
@require_auth
def reject_tone_profile(client_id, profile_id):
    """Mark a pending profile as rejected. Kept in history but never active.

    Ben's ask, 2026-09-08: accept an optional free-text reason for the
    rejection. This is much higher-signal than the auto-inferred
    rejection_list -- it's Ben's own judgment about why the proposal missed,
    not Claude's guess -- and gets fed back into future Delta Analyzer runs
    for this client/context (see build_delta_analysis_prompt's
    rejected_context param) so the model doesn't repeat the same mistake."""
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()

    db = get_db()
    row = db.execute(
        'SELECT id, is_active FROM tone_profiles WHERE id = ? AND client_id = ?',
        (profile_id, client_id)
    ).fetchone()
    if not row:
        return jsonify({'error': {'message': 'Profile not found for this client.'}}), 404
    if row['is_active']:
        return jsonify({'error': {'message': 'This profile is currently active; activate a different version before rejecting.'}}), 400
    db.execute(
        "UPDATE tone_profiles SET status = 'rejected', rejection_reason = ? WHERE id = ?",
        (reason, profile_id)
    )
    db.commit()
    return jsonify({'ok': True})


# ---------- Delta Analyzer (Phase 3, Ben's ask 2026-09-03) ----------
# Box A (original post) / Box B (client's edit) -> propose an updated Tone
# Profile version (pending, same activate/reject flow as Phase 1) + attempt
# to regenerate the same topic using it, so Ben can eyeball how close it
# got. See prompts.py's Delta Analyzer section and db.py's tone_deltas
# comment for the reasoning (no self-graded match score -- Ben judges).

def _extract_json_object(raw):
    """Same defensive fence-stripping as create_tone_profile() -- the
    prompt asks for pure JSON but strip accidental markdown fences."""
    cleaned = (raw or '').strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.strip('`')
        if cleaned.lower().startswith('json'):
            cleaned = cleaned[4:].strip()
    return json.loads(cleaned)


@app.route('/api/clients/<int:client_id>/tone-profiles/delta', methods=['POST'])
@require_auth
def run_delta_analyzer(client_id):
    """Step 1+2 combined: analyze the original/edit pair against the
    current active profile, propose an updated version (pending), then
    immediately attempt a regeneration of the same topic using it."""
    data = request.get_json() or {}
    context = (data.get('context') or 'default').strip() or 'default'
    original_post = (data.get('original_post') or '').strip()
    client_edit = (data.get('client_edit') or '').strip()

    if len(original_post) < 20 or len(client_edit) < 20:
        return jsonify({'error': {'message': 'Both the original post and the client\'s edit are required (min 20 chars each).'}}), 400

    db = get_db()
    if not db.execute('SELECT id FROM clients WHERE id = ?', (client_id,)).fetchone():
        return jsonify({'error': {'message': 'Client not found.'}}), 404

    active = db.execute(
        'SELECT * FROM tone_profiles WHERE client_id = ? AND context = ? AND is_active = 1',
        (client_id, context)
    ).fetchone()
    if not active:
        return jsonify({'error': {'message': f'No active Tone Profile for context "{context}" yet -- generate and activate one first (Phase 1) before running the Delta Analyzer.'}}), 400

    # Pull recent rejections for this client/context so the analysis prompt
    # doesn't repeat a direction Ben already said no to (Ben's ask, 2026-09-08).
    rejected_rows = db.execute(
        "SELECT change_summary, rejection_reason FROM tone_profiles "
        "WHERE client_id = ? AND context = ? AND status = 'rejected' "
        "ORDER BY created_at DESC LIMIT 5",
        (client_id, context)
    ).fetchall()
    rejected_context = [dict(r) for r in rejected_rows]

    # Step 1: analyze the diff, propose an updated profile.
    system, user = build_delta_analysis_prompt(
        original_post, client_edit, active['profile_json'], context=context,
        rejected_context=rejected_context,
    )
    try:
        raw = call_anthropic(model='claude-sonnet-4-5', max_tokens=4000, system=system,
                             messages=[{'role': 'user', 'content': user}])
        result = _extract_json_object(raw)
    except json.JSONDecodeError as e:
        return jsonify({'error': {'message': f'Model returned invalid JSON for the profile update: {e}'}}), 502
    except Exception as e:
        return jsonify({'error': {'message': f'Delta analysis failed: {e}'}}), 502

    diff_analysis = result.pop('diff_analysis', '')
    rejection_additions = result.pop('rejection_additions', []) or []
    updated_profile = result  # whatever's left is the profile fields (summary, voice_do, categories, etc.)

    # Merge rejection lists -- union, dedup, preserve order (old entries first).
    try:
        old_rejections = json.loads(active['rejection_list'] or '[]')
    except (TypeError, ValueError):
        old_rejections = []
    merged_rejections = list(old_rejections)
    for item in rejection_additions:
        if item not in merged_rejections:
            merged_rejections.append(item)

    # source_mix: the client's own edit is real written-voice evidence --
    # carry the parent's mix forward and add the edit's length to written_chars.
    try:
        parent_mix = json.loads(active['source_mix'] or '{}')
    except (TypeError, ValueError):
        parent_mix = {}
    source_mix = {
        'spoken_chars': parent_mix.get('spoken_chars', 0),
        'written_chars': parent_mix.get('written_chars', 0) + len(client_edit),
    }

    next_version = active['version'] + 1
    source_text = f'ORIGINAL:\n{original_post}\n\n---CLIENT EDIT---\n{client_edit}'
    profile_json_str = json.dumps(updated_profile, ensure_ascii=False)

    # example_posts/target_length (Ben's ask, 2026-09-08): the client's own
    # edit is real, verbatim voice evidence -- accumulate it (capped at 3,
    # most recent) as a raw exemplar alongside the scored profile, and derive
    # a length target from it since Hemingway has been running long.
    example_posts_json = _merge_example_posts(active['example_posts'], client_edit)
    target_length_json = _compute_target_length(example_posts_json)

    cur = db.execute(
        'INSERT INTO tone_profiles (client_id, context, version, source_type, source_text, '
        'profile_json, rejection_list, source_mix, change_summary, parent_version, status, is_active, '
        'example_posts, target_length) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (client_id, context, next_version, 'delta', source_text, profile_json_str,
         json.dumps(merged_rejections), json.dumps(source_mix), diff_analysis, active['version'], 'pending', 0,
         example_posts_json, target_length_json)
    )
    db.commit()
    new_profile_id = cur.lastrowid

    # Step 2: attempt to regenerate the same topic using the proposed profile.
    #
    # BUG FIXED 2026-09-08 (Ben caught this in real use -- regenerations were
    # just repeating one client post verbatim regardless of the post's topic):
    # example_posts_json above already has THIS pair's client_edit merged in.
    # Handing that straight to the regeneration call means the model is shown
    # the exact answer it's being tested against and, unsurprisingly, just
    # pastes it back. The regen step must only see examples that predate this
    # test -- current pair's client_edit is excluded here, added back for
    # everything downstream (real generation, future delta runs) once this
    # version is stored/activated, where it's legitimately historical.
    regen_only_examples = [e for e in json.loads(example_posts_json) if e != client_edit]
    regen_system = build_system_prompt(
        'conversational', client_rules='', active_tone_profile=updated_profile,
        example_posts=regen_only_examples, target_length=json.loads(target_length_json),
    )
    regen_user = build_delta_regenerate_user_prompt(original_post)
    try:
        regenerated_attempt = call_anthropic(model='claude-sonnet-4-5', max_tokens=1200,
                                             system=regen_system, messages=[{'role': 'user', 'content': regen_user}])
    except Exception as e:
        regenerated_attempt = f'(regeneration failed: {e})'

    delta_cur = db.execute(
        'INSERT INTO tone_deltas (client_id, context, original_post, client_edit, diff_analysis, '
        'resulting_version, regenerated_attempt) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (client_id, context, original_post, client_edit, diff_analysis, next_version, regenerated_attempt)
    )
    db.commit()
    delta_id = delta_cur.lastrowid

    new_profile_row = db.execute('SELECT * FROM tone_profiles WHERE id = ?', (new_profile_id,)).fetchone()
    delta_row = db.execute('SELECT * FROM tone_deltas WHERE id = ?', (delta_id,)).fetchone()
    return jsonify({'tone_profile': dict(new_profile_row), 'delta': dict(delta_row)})


@app.route('/api/clients/<int:client_id>/tone-profiles/deltas/<int:delta_id>/regenerate-again', methods=['POST'])
@require_auth
def regenerate_delta_again(client_id, delta_id):
    """Retry JUST the regeneration attempt using the SAME pending profile
    version -- doesn't re-run the diff analysis. This is the 'Regenerate'
    retry button: try again until it's close enough, or give up and reject."""
    db = get_db()
    delta = db.execute('SELECT * FROM tone_deltas WHERE id = ? AND client_id = ?', (delta_id, client_id)).fetchone()
    if not delta:
        return jsonify({'error': {'message': 'Delta attempt not found for this client.'}}), 404

    profile_row = db.execute(
        'SELECT * FROM tone_profiles WHERE client_id = ? AND context = ? AND version = ?',
        (client_id, delta['context'], delta['resulting_version'])
    ).fetchone()
    if not profile_row:
        return jsonify({'error': {'message': 'The proposed profile version for this attempt no longer exists.'}}), 404

    try:
        updated_profile = json.loads(profile_row['profile_json'])
    except (TypeError, ValueError):
        return jsonify({'error': {'message': 'Stored profile JSON is corrupt.'}}), 500

    try:
        example_posts = json.loads(profile_row['example_posts'] or '[]')
    except (TypeError, ValueError):
        example_posts = []
    try:
        target_length = json.loads(profile_row['target_length'] or '{}')
    except (TypeError, ValueError):
        target_length = {}

    # Same leakage fix as run_delta_analyzer -- this pending profile's own
    # example_posts includes THIS delta's client_edit (the answer), which
    # must never be shown to the regeneration call it's being tested against.
    regen_only_examples = [e for e in example_posts if e != delta['client_edit']]

    regen_system = build_system_prompt(
        'conversational', client_rules='', active_tone_profile=updated_profile,
        example_posts=regen_only_examples, target_length=target_length,
    )
    regen_user = build_delta_regenerate_user_prompt(delta['original_post'])
    try:
        regenerated_attempt = call_anthropic(model='claude-sonnet-4-5', max_tokens=1200,
                                             system=regen_system, messages=[{'role': 'user', 'content': regen_user}])
    except Exception as e:
        return jsonify({'error': {'message': f'Regeneration failed: {e}'}}), 502

    db.execute('UPDATE tone_deltas SET regenerated_attempt = ? WHERE id = ?', (regenerated_attempt, delta_id))
    db.commit()
    updated = db.execute('SELECT * FROM tone_deltas WHERE id = ?', (delta_id,)).fetchone()
    return jsonify(dict(updated))


@app.route('/api/clients/<int:client_id>/tone-profiles/deltas', methods=['GET'])
@require_auth
def list_deltas(client_id):
    context = request.args.get('context')
    db = get_db()
    if context:
        rows = db.execute(
            'SELECT * FROM tone_deltas WHERE client_id = ? AND context = ? ORDER BY created_at DESC',
            (client_id, context)
        ).fetchall()
    else:
        rows = db.execute(
            'SELECT * FROM tone_deltas WHERE client_id = ? ORDER BY created_at DESC', (client_id,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


# ---------- Opener Library (Ben's ask, 2026-09-09) ----------
# Freeform, manually-curated bank of confirmed-good openers, decoupled from
# any post record or publish status (Harris posts via Hey Orca, not Postiz,
# so Studio has no automatic "this went live" signal). See db.py's
# opener_library comment.

@app.route('/api/clients/<int:client_id>/opener-library', methods=['GET'])
@require_auth
def list_opener_library(client_id):
    context = request.args.get('context', 'default')
    db = get_db()
    rows = db.execute(
        'SELECT id, client_id, context, opener_text, created_at FROM opener_library '
        'WHERE client_id = ? AND context = ? ORDER BY created_at DESC',
        (client_id, context)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/clients/<int:client_id>/opener-library', methods=['POST'])
@require_auth
def add_opener_library_entry(client_id):
    data = request.get_json() or {}
    opener_text = (data.get('opener_text') or '').strip()
    context = (data.get('context') or 'default').strip() or 'default'
    if len(opener_text) < 5:
        return jsonify({'error': {'message': 'Opener text is too short.'}}), 400
    db = get_db()
    if not db.execute('SELECT id FROM clients WHERE id = ?', (client_id,)).fetchone():
        return jsonify({'error': {'message': 'Client not found.'}}), 404
    cur = db.execute(
        'INSERT INTO opener_library (client_id, context, opener_text) VALUES (?, ?, ?)',
        (client_id, context, opener_text)
    )
    db.commit()
    row = db.execute('SELECT * FROM opener_library WHERE id = ?', (cur.lastrowid,)).fetchone()
    return jsonify(dict(row))


@app.route('/api/clients/<int:client_id>/opener-library/<int:entry_id>', methods=['DELETE'])
@require_auth
def delete_opener_library_entry(client_id, entry_id):
    db = get_db()
    row = db.execute(
        'SELECT id FROM opener_library WHERE id = ? AND client_id = ?', (entry_id, client_id)
    ).fetchone()
    if not row:
        return jsonify({'error': {'message': 'Entry not found for this client.'}}), 404
    db.execute('DELETE FROM opener_library WHERE id = ?', (entry_id,))
    db.commit()
    return jsonify({'ok': True})


# ---------- Style Docs ----------

@app.route('/api/clients/<int:client_id>/style-docs', methods=['GET'])
@app.route('/api/clients/<int:client_id>/docs', methods=['GET'])
@require_auth
def get_style_docs(client_id):
    db = get_db()
    rows = db.execute(
        'SELECT id, client_id, filename, created_at FROM style_docs WHERE client_id = ? ORDER BY created_at DESC',
        (client_id,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/clients/<int:client_id>/style-docs', methods=['POST'])
@app.route('/api/clients/<int:client_id>/docs', methods=['POST'])
@require_auth
def upload_style_doc(client_id):
    db = get_db()
    if not db.execute('SELECT id FROM clients WHERE id = ?', (client_id,)).fetchone():
        return jsonify({'error': {'message': 'Client not found.'}}), 404
    # Frontend sends files under 'files' (plural); also accept 'file' (singular)
    files = request.files.getlist('files') or request.files.getlist('file')
    if not files or not files[0].filename:
        return jsonify({'error': {'message': 'No file provided.'}}), 400
    saved = []
    for file in files:
        if not file.filename:
            continue
        content = file.read().decode('utf-8', errors='replace')
        cursor = db.execute(
            'INSERT INTO style_docs (client_id, filename, content) VALUES (?, ?, ?)',
            (client_id, file.filename, content)
        )
        db.commit()
        row = db.execute(
            'SELECT id, client_id, filename, created_at FROM style_docs WHERE id = ?',
            (cursor.lastrowid,)
        ).fetchone()
        saved.append(dict(row))
    return jsonify(saved[0] if len(saved) == 1 else saved), 201


@app.route('/api/style-docs/<int:doc_id>', methods=['DELETE'])
@app.route('/api/docs/<int:doc_id>', methods=['DELETE'])
@require_auth
def delete_style_doc(doc_id):
    db = get_db()
    db.execute('DELETE FROM style_docs WHERE id = ?', (doc_id,))
    db.commit()
    return jsonify({'ok': True})


# ---------- Batches ----------

@app.route('/api/clients/<int:client_id>/batches', methods=['GET'])
@require_auth
def get_batches(client_id):
    db = get_db()
    rows = db.execute(
        'SELECT id, name, style, length, context, created_at FROM batches WHERE client_id = ? ORDER BY created_at DESC',
        (client_id,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/batches/<int:batch_id>', methods=['GET'])
@require_auth
def get_batch(batch_id):
    db = get_db()
    row = db.execute(
        'SELECT id, client_id, transcript_raw, name, style, length, context, created_at FROM batches WHERE id = ?',
        (batch_id,)
    ).fetchone()
    if not row:
        return jsonify({'error': {'message': 'Batch not found.'}}), 404
    return jsonify(dict(row))


@app.route('/api/batches/<int:batch_id>/posts', methods=['GET'])
@require_auth
def get_batch_posts(batch_id):
    db = get_db()
    rows = db.execute(
        'SELECT id, title, body, section_body FROM posts WHERE batch_id = ? ORDER BY id ASC',
        (batch_id,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/batches/<int:batch_id>', methods=['DELETE'])
@require_auth
def delete_batch(batch_id):
    db = get_db()
    db.execute('DELETE FROM batches WHERE id = ?', (batch_id,))
    db.commit()
    return jsonify({'ok': True})


# ---------- Anthropic ----------

def call_anthropic(model, max_tokens, system, messages):
    client = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages
    )
    text_block = next((b for b in message.content if b.type == 'text'), None)
    return text_block.text if text_block else ''


def get_active_tone_profile(client_id, context='default'):
    """Fetch the currently-active Tone Profile for (client, context) and
    return it as a parsed dict, or None if none is active. Follows the same
    same-request-caller pattern as get_global_style so both must be fetched
    BEFORE entering generate()'s stream() closure (which loses g.db).
    Phase 2 (Ben's ask 2026-08-27) wires this into prompt construction."""
    db = get_db()
    row = db.execute(
        'SELECT profile_json FROM tone_profiles WHERE client_id = ? AND context = ? AND is_active = 1',
        (client_id, context or 'default')
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row['profile_json'])
    except (TypeError, ValueError):
        return None


def _extract_opening_line(text):
    """Grab just the opening sentence/line of a post body -- used both to
    record what a post opened with (for the anti-repetition check) and when
    rendering opener_library entries. Simple heuristic: first line, or up to
    the first sentence-ending punctuation if the first line is long."""
    if not text:
        return ''
    first_line = text.strip().split('\n')[0].strip()
    for punct in ('. ', '! ', '? '):
        idx = first_line.find(punct)
        if 0 < idx < 200:
            return first_line[:idx + 1].strip()
    return first_line[:200].strip()


def get_recent_openers(client_id, context='default', limit=3):
    """Last N real posts' opening lines for this client/context (Ben's ask,
    2026-09-09). Each generation call is otherwise stateless -- it has no
    memory of any other post, including ones written minutes ago -- so
    without this, nothing stops the model from reusing the same opener
    structure every time. Looked up against Hemingway's own posts table via
    the batches this client owns (posts have no direct client_id column)."""
    db = get_db()
    rows = db.execute(
        'SELECT p.body FROM posts p JOIN batches b ON p.batch_id = b.id '
        'WHERE b.client_id = ? ORDER BY p.created_at DESC LIMIT ?',
        (client_id, limit)
    ).fetchall()
    return [_extract_opening_line(r['body']) for r in rows if r['body']]


def get_opener_library(client_id, context='default', limit=10):
    """Manually-curated bank of confirmed-good openers (Ben's ask,
    2026-09-09) -- see db.py's opener_library comment for why this is a
    freeform paste rather than tied to any post/publish status."""
    db = get_db()
    rows = db.execute(
        'SELECT opener_text FROM opener_library WHERE client_id = ? AND context = ? '
        'ORDER BY created_at DESC LIMIT ?',
        (client_id, context or 'default', limit)
    ).fetchall()
    return [r['opener_text'] for r in rows]


def get_active_tone_extras(client_id, context='default'):
    """Companion to get_active_tone_profile() -- fetches the same active
    row's example_posts/target_length (Ben's ask, 2026-09-08). Kept separate
    rather than folded into get_active_tone_profile() so that function's
    existing return shape (just the parsed profile dict) doesn't change for
    its other callers/tests. Same before-stream()/g.db caveat applies."""
    db = get_db()
    row = db.execute(
        'SELECT example_posts, target_length FROM tone_profiles WHERE client_id = ? AND context = ? AND is_active = 1',
        (client_id, context or 'default')
    ).fetchone()
    if not row:
        return [], {}
    try:
        example_posts = json.loads(row['example_posts'] or '[]')
    except (TypeError, ValueError):
        example_posts = []
    try:
        target_length = json.loads(row['target_length'] or '{}')
    except (TypeError, ValueError):
        target_length = {}
    return example_posts, target_length


def review_and_revise_post(draft, style, client_rules, style_docs_text, global_style=None, active_tone_profile=None, example_posts=None, target_length=None, recent_openers=None, library_openers=None, opener_shape_candidates=None):
    """Second pass: an independent editor call that checks the first pass's
    output against the same style/voice standards it was supposed to follow,
    and fixes anything that slipped through. Best-effort — if this call fails
    for any reason, the caller should fall back to the unreviewed draft rather
    than losing the post entirely.

    global_style is {'global_style_doc', 'base_rules'} from get_global_style()
    -- passed in rather than fetched here because this is sometimes called
    from inside generate()'s stream() generator, which runs after Flask has
    already handed off the response and closed the request-bound `g.db`
    connection get_global_style() would otherwise need."""
    global_style = global_style or {}
    system = build_review_system_prompt(
        style, client_rules,
        global_style_doc=global_style.get('global_style_doc'),
        base_rules=global_style.get('base_rules'),
        active_tone_profile=active_tone_profile,
        example_posts=example_posts,
        target_length=target_length,
        recent_openers=recent_openers,
        library_openers=library_openers,
        opener_shape_candidates=opener_shape_candidates,
    )
    user = build_review_user_prompt(draft, style_docs_text)
    revised = call_anthropic(
        model='claude-sonnet-4-5',
        max_tokens=1200,
        system=system,
        messages=[{'role': 'user', 'content': user}]
    )
    return revised.strip() or draft


def write_post_for_section(title, section_body, full_corpus, style, length, client_rules, style_docs_text, batch_context, global_style=None, active_tone_profile=None, example_posts=None, target_length=None, recent_openers=None, library_openers=None, opener_shape_candidates=None):
    global_style = global_style or {}
    system = build_system_prompt(
        style, client_rules,
        global_style_doc=global_style.get('global_style_doc'),
        base_rules=global_style.get('base_rules'),
        active_tone_profile=active_tone_profile,
        example_posts=example_posts,
        target_length=target_length,
        recent_openers=recent_openers,
        library_openers=library_openers,
        opener_shape_candidates=opener_shape_candidates,
    )
    # Phase 2: when a Tone Profile is active it fully replaces the manual
    # style_rules/reference-copy layer, so DON'T include either of those in
    # the user prompt -- passing them in as reference material would leak the
    # exact voice signal we're trying to test the profile against, and would
    # muddy the Phase 3 delta validation Ben plans against Harris's 9 pairs.
    user_style_docs = '' if active_tone_profile else style_docs_text
    user_client_rules = '' if active_tone_profile else client_rules
    user = build_user_prompt(title, section_body, full_corpus, length, user_style_docs, batch_context, user_client_rules)
    draft = call_anthropic(
        model='claude-sonnet-4-5',
        max_tokens=1200,
        system=system,
        messages=[{'role': 'user', 'content': user}]
    )
    try:
        return review_and_revise_post(draft, style, client_rules, style_docs_text, global_style, active_tone_profile=active_tone_profile, example_posts=example_posts, target_length=target_length, recent_openers=recent_openers, library_openers=library_openers, opener_shape_candidates=opener_shape_candidates)
    except Exception:
        # Style QA pass is best-effort -- a working, unreviewed post beats no post.
        return draft


# ---------- Generate (streaming) ----------

@app.route('/api/generate', methods=['POST'])
@require_auth
def generate():
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': {'message': 'Server is missing ANTHROPIC_API_KEY. Contact the admin.'}}), 500

    data = request.get_json() or {}
    client_id = data.get('clientId')
    transcript = data.get('transcript')
    style = data.get('style')
    length = data.get('length')
    context = data.get('context', '')
    # Ben's ask 2026-08-27: tone_context selects WHICH Tone Profile this batch
    # uses (default / event / podcast / founder-profile / etc.). Distinct from
    # `context`, which is free-form batch background text for the model.
    tone_context = (data.get('tone_context') or 'default').strip() or 'default'
    name = data.get('name', '').strip()
    # 'transcript' (default) = Degas format with VIDEO: headers/timestamps.
    # 'plain' = Ben's ask 2026-08-24: type "Post 1: ..." blocks directly,
    # no Degas export needed. See split_transcript_plain() in prompts.py.
    input_format = data.get('format', 'transcript')

    if not all([client_id, transcript, style, length]):
        return jsonify({'error': {'message': 'Missing required fields.'}}), 400

    db = get_db()
    client = db.execute('SELECT * FROM clients WHERE id = ?', (client_id,)).fetchone()
    if not client:
        return jsonify({'error': {'message': 'Client not found.'}}), 404

    if input_format == 'plain':
        sections = split_transcript_plain(transcript)
        if not sections:
            return jsonify({'error': {'message': 'No posts detected. Make sure each one starts with "Post 1:", "Post 2:", etc.'}}), 400
    else:
        sections = split_transcript(transcript)
        if not sections:
            return jsonify({'error': {'message': 'No video sections detected. Make sure this is a Degas transcript with VIDEO: headers.'}}), 400

    docs = db.execute('SELECT content FROM style_docs WHERE client_id = ?', (client_id,)).fetchall()
    style_docs_text = '\n\n---\n\n'.join(r['content'] for r in docs)
    client_rules = client['style_rules'] or ''
    # Fetched once here, before stream() -- not inside it, since get_global_style()
    # needs the request-bound g.db/get_db(), which is gone once Flask hands off
    # the streaming response (see stream()'s own comment on its dedicated connection).
    global_style = get_global_style()
    # Same reason as global_style: must fetch BEFORE stream() -- get_db()/g.db
    # is gone once Flask hands off the streaming response.
    active_tone_profile = get_active_tone_profile(client_id, tone_context)
    example_posts, target_length = get_active_tone_extras(client_id, tone_context)
    # Ben's ask 2026-09-09: opener rotation. recent_openers seeds the batch
    # with what was ALREADY used in real prior posts; batch_openers (below,
    # inside stream()) then grows as this batch itself writes posts, so post
    # 5 of 8 in one run knows what posts 1-4 in the SAME run just opened
    # with -- otherwise every post in a batch is blind to every other post
    # in that same batch, which is the main reason openers kept repeating.
    recent_openers = get_recent_openers(client_id, tone_context)
    library_openers = get_opener_library(client_id, tone_context)
    # Ben's ask 2026-09-10 (round 1): the original "pick one shape, rotate"
    # instruction was too soft -- in production the model gravitated to the
    # same 1-2 shapes (or invented its own opener not even in the list)
    # across a 10-post batch instead of actually rotating.
    #
    # Ben's ask 2026-09-10 (round 2): forcing exactly ONE shape per post (the
    # first fix) over-corrected -- it produced posts where a shape got forced
    # onto a topic it had nothing to do with (a Gulf Coast humidity/conditions
    # shape bolted onto a post about a kitchen layout). Model discretion was
    # the problem AND the solution: it needs SOME choice to judge topical fit,
    # just not all 25 options (that's what caused round 1's non-rotation).
    #
    # Fix: a small ROTATING WINDOW of candidate shapes per post (see
    # OPENER_SHAPE_CANDIDATE_WINDOW below) -- narrow enough to force real
    # variety across a batch (each post sees a different slice), wide enough
    # that the model can pick whichever of 2-3 options actually fits this
    # post's real topic instead of forcing a bad match.
    OPENER_SHAPE_CANDIDATE_WINDOW = 3
    opener_shape_rotation = list((active_tone_profile or {}).get('opener_shapes') or [])
    if opener_shape_rotation:
        random.shuffle(opener_shape_rotation)

    # Cap the voice-context corpus at 10 sections to control token costs on large batches.
    # The model only needs a sample to learn the speaker's voice — all 40+ sections is wasteful.
    CORPUS_SECTION_CAP = 10
    if len(sections) > CORPUS_SECTION_CAP:
        capped_sections = sections[:CORPUS_SECTION_CAP]
        corpus_for_context = '\n\n'.join(f"VIDEO: {s['title']}\n{s['body']}" for s in capped_sections)
    else:
        corpus_for_context = transcript

    cursor = db.execute(
        'INSERT INTO batches (client_id, transcript_raw, name, style, length, context) VALUES (?, ?, ?, ?, ?, ?)',
        (client_id, transcript, name, style, length, context)
    )
    db.commit()
    batch_id = cursor.lastrowid

    def stream():
        # Open a dedicated connection — g.db is closed when Flask hands off the
        # streaming response, before this generator finishes.
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        batch_openers = []  # opening lines of posts already written IN THIS batch
        try:
            yield json.dumps({'type': 'start', 'batchId': batch_id, 'total': len(sections)}) + '\n'
            for i, sec in enumerate(sections):
                try:
                    shape_candidates = None
                    if opener_shape_rotation:
                        L = len(opener_shape_rotation)
                        w = min(OPENER_SHAPE_CANDIDATE_WINDOW, L)
                        # Non-overlapping w-sized chunks through the shuffled
                        # list, wrapping around -- guarantees each shape shows
                        # up as a candidate roughly once per lap through the
                        # full list, instead of the same 2-3 shapes getting
                        # offered every single post.
                        start = (i * w) % L
                        shape_candidates = [opener_shape_rotation[(start + j) % L] for j in range(w)]
                    post = write_post_for_section(
                        sec['title'], sec['body'], corpus_for_context,
                        style, length, client_rules,
                        style_docs_text, context, global_style,
                        active_tone_profile=active_tone_profile,
                        example_posts=example_posts,
                        target_length=target_length,
                        recent_openers=recent_openers + batch_openers,
                        library_openers=library_openers,
                        opener_shape_candidates=shape_candidates,
                    )
                    batch_openers.append(_extract_opening_line(post))
                    post_cursor = conn.execute(
                        'INSERT INTO posts (batch_id, title, body, section_body) VALUES (?, ?, ?, ?)',
                        (batch_id, sec['title'], post, sec['body'])
                    )
                    conn.commit()
                    yield json.dumps({'type': 'post', 'index': i, 'id': post_cursor.lastrowid, 'title': sec['title'], 'body': post, 'error': None}) + '\n'
                except Exception as e:
                    yield json.dumps({'type': 'post', 'index': i, 'id': None, 'title': sec['title'], 'body': '', 'error': str(e)}) + '\n'
            yield json.dumps({'type': 'done'}) + '\n'
        finally:
            conn.close()

    resp = Response(stream_with_context(stream()), mimetype='application/x-ndjson')
    resp.headers['X-Accel-Buffering'] = 'no'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


# ---------- Rewrite ----------

@app.route('/api/posts/<int:post_id>/rewrite', methods=['POST'])
@require_auth
def rewrite_post(post_id):
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': {'message': 'Server is missing ANTHROPIC_API_KEY.'}}), 500

    db = get_db()
    post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    if not post:
        return jsonify({'error': {'message': 'Post not found.'}}), 404

    batch = db.execute('SELECT * FROM batches WHERE id = ?', (post['batch_id'],)).fetchone()
    client = db.execute('SELECT * FROM clients WHERE id = ?', (batch['client_id'],)).fetchone()
    docs = db.execute('SELECT content FROM style_docs WHERE client_id = ?', (client['id'],)).fetchall()
    style_docs_text = '\n\n---\n\n'.join(r['content'] for r in docs)

    data = request.get_json() or {}
    extra = (data.get('instruction') or '').strip()
    client_rules = client['style_rules'] or ''
    if extra:
        client_rules += f'\n\nFor this specific rewrite, also follow this instruction: {extra}'

    try:
        _rewrite_example_posts, _rewrite_target_length = get_active_tone_extras(client['id'])
        _rewrite_profile = get_active_tone_profile(client['id'])
        # No batch to round-robin against here (single post) -- offer a small
        # random menu (same reasoning as generate()'s sliding window: forcing
        # exactly one shape produced topically-forced posts, so let the model
        # pick whichever of a few options actually fits this post).
        _rewrite_shapes = (_rewrite_profile or {}).get('opener_shapes') or []
        _rewrite_candidates = (
            random.sample(_rewrite_shapes, min(3, len(_rewrite_shapes)))
            if _rewrite_shapes else None
        )
        new_body = write_post_for_section(
            post['title'], post['section_body'], batch['transcript_raw'],
            batch['style'], batch['length'], client_rules,
            style_docs_text, batch['context'], get_global_style(),
            active_tone_profile=_rewrite_profile,
            example_posts=_rewrite_example_posts,
            target_length=_rewrite_target_length,
            recent_openers=get_recent_openers(client['id']),
            library_openers=get_opener_library(client['id']),
            opener_shape_candidates=_rewrite_candidates,
        )
        db.execute('UPDATE posts SET body = ? WHERE id = ?', (new_body, post_id))
        db.commit()
        return jsonify({'id': post_id, 'title': post['title'], 'body': new_body})
    except Exception as e:
        return jsonify({'error': {'message': str(e)}}), 500


# ---------- Rewrite Paragraph ----------

@app.route('/api/posts/<int:post_id>/rewrite-paragraph', methods=['POST'])
@require_auth
def rewrite_paragraph(post_id):
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': {'message': 'Server is missing ANTHROPIC_API_KEY.'}}), 500

    db = get_db()
    post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    if not post:
        return jsonify({'error': {'message': 'Post not found.'}}), 404

    batch = db.execute('SELECT * FROM batches WHERE id = ?', (post['batch_id'],)).fetchone()
    client = db.execute('SELECT * FROM clients WHERE id = ?', (batch['client_id'],)).fetchone()

    data = request.get_json() or {}
    paragraph_index = data.get('paragraphIndex')
    instruction = data.get('instruction', '')

    paragraphs = post['body'].split('\n\n')
    if paragraph_index is None or not (0 <= paragraph_index < len(paragraphs)):
        return jsonify({'error': {'message': 'Invalid paragraph index.'}}), 400

    target = paragraphs[paragraph_index]
    global_style = get_global_style()
    active_tone_profile = get_active_tone_profile(client['id'])
    example_posts, target_length = get_active_tone_extras(client['id'])
    system = (
        build_system_prompt(
            batch['style'], client['style_rules'],
            global_style_doc=global_style['global_style_doc'],
            base_rules=global_style['base_rules'],
            active_tone_profile=active_tone_profile,
            example_posts=example_posts,
            target_length=target_length,
        ) +
        '\n\nYou are revising ONE paragraph of an existing LinkedIn post. Keep it consistent '
        'with the rest of the post in tone and voice. Output ONLY the rewritten paragraph text, nothing else.'
    )
    user = (
        f'Full post for context:\n\n{post["body"]}\n\n---\n\n'
        f'The paragraph to rewrite:\n\n"{target}"\n\n'
        + (f'Instruction: {instruction}' if instruction else 'Rewrite this paragraph to be stronger, while keeping the same core point.')
        + '\n\nOutput only the new paragraph text.'
    )

    try:
        result = call_anthropic(
            model='claude-sonnet-4-5',
            max_tokens=400,
            system=system,
            messages=[{'role': 'user', 'content': user}]
        )
        new_paragraph = result.strip() or target
        paragraphs[paragraph_index] = new_paragraph
        new_body = '\n\n'.join(paragraphs)
        db.execute('UPDATE posts SET body = ? WHERE id = ?', (new_body, post_id))
        db.commit()
        return jsonify({'id': post_id, 'body': new_body, 'paragraph': new_paragraph})
    except Exception as e:
        return jsonify({'error': {'message': str(e)}}), 500


# ---------- Serve frontend ----------

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')


if __name__ == '__main__':
    print(f'Hemingway running on port {PORT}')
    if not ANTHROPIC_API_KEY:
        print('WARNING: ANTHROPIC_API_KEY is not set. Generation will fail until it is configured.')
    app.run(host='0.0.0.0', port=PORT, debug=False)
