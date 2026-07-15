import os
import json
import sqlite3
from functools import wraps
from flask import Flask, request, session, jsonify, send_from_directory, Response, stream_with_context
from dotenv import load_dotenv
import anthropic as anthropic_sdk
from db import init_db, get_db, close_db, DB_PATH
from prompts import build_system_prompt, build_user_prompt, split_transcript

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


def write_post_for_section(title, section_body, full_corpus, style, length, client_rules, style_docs_text, batch_context):
    system = build_system_prompt(style, client_rules)
    user = build_user_prompt(title, section_body, full_corpus, length, style_docs_text, batch_context, client_rules)
    return call_anthropic(
        model='claude-sonnet-4-5',
        max_tokens=1200,
        system=system,
        messages=[{'role': 'user', 'content': user}]
    )


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
    name = data.get('name', '').strip()

    if not all([client_id, transcript, style, length]):
        return jsonify({'error': {'message': 'Missing required fields.'}}), 400

    db = get_db()
    client = db.execute('SELECT * FROM clients WHERE id = ?', (client_id,)).fetchone()
    if not client:
        return jsonify({'error': {'message': 'Client not found.'}}), 404

    sections = split_transcript(transcript)
    if not sections:
        return jsonify({'error': {'message': 'No video sections detected. Make sure this is a Degas transcript with VIDEO: headers.'}}), 400

    docs = db.execute('SELECT content FROM style_docs WHERE client_id = ?', (client_id,)).fetchall()
    style_docs_text = '\n\n---\n\n'.join(r['content'] for r in docs)
    client_rules = client['style_rules'] or ''

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
        try:
            yield json.dumps({'type': 'start', 'batchId': batch_id, 'total': len(sections)}) + '\n'
            for i, sec in enumerate(sections):
                try:
                    post = write_post_for_section(
                        sec['title'], sec['body'], transcript,
                        style, length, client_rules,
                        style_docs_text, context
                    )
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
        new_body = write_post_for_section(
            post['title'], post['section_body'], batch['transcript_raw'],
            batch['style'], batch['length'], client_rules,
            style_docs_text, batch['context']
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
    system = (
        build_system_prompt(batch['style'], client['style_rules']) +
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
