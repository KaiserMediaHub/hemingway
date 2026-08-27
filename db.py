import sqlite3
import os
from flask import g

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, 'hemingway.db')

SCHEMA = '''
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    style_rules TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS style_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    transcript_raw TEXT NOT NULL,
    style TEXT NOT NULL,
    length TEXT NOT NULL,
    context TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    section_body TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE
);

-- Tone Profile system (Ben's ask, 2026-08-27) -- versioned voice profiles
-- per client and per context (default / event / podcast / founder-profile /
-- etc.). Phase 1: profiles are generated and stored, but not yet wired into
-- post generation -- that's Phase 2. Phase 3 adds the Delta Analyzer that
-- learns from client edits and proposes new versions. Every version is kept
-- forever so revert is trivial. Only one version per (client, context) is
-- `is_active` at a time; new pending versions require Ben's approval before
-- becoming active (protects against a single bad transcript silently
-- warping the profile).
CREATE TABLE IF NOT EXISTS tone_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    context TEXT NOT NULL DEFAULT 'default',    -- 'default', 'event', 'podcast', etc.
    version INTEGER NOT NULL,                   -- monotonically increasing per (client, context)
    source_type TEXT NOT NULL,                  -- 'transcript', 'posts', 'delta', 'auto-transcript-queued'
    source_text TEXT NOT NULL,                  -- the raw material fed in (transcript or posts)
    profile_json TEXT NOT NULL,                 -- structured categories + confidence + supporting quotes
    rejection_list TEXT DEFAULT '[]',           -- JSON array; empty on v1, grows via Delta Analyzer (Phase 3)
    source_mix TEXT DEFAULT '{}',               -- running tally: {"spoken_chars": N, "written_chars": N}
    change_summary TEXT DEFAULT '',             -- plain-language note about what changed vs. parent version
    parent_version INTEGER,                     -- NULL for v1; else the version number this was derived from
    status TEXT NOT NULL DEFAULT 'pending',     -- 'pending' | 'approved' | 'rejected'
    is_active INTEGER NOT NULL DEFAULT 0,       -- 0/1; enforced by app.py, not DB (only one per client+context)
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

-- Single-row table for the rules that apply to EVERY client (Ben's ask,
-- 2026-08-24: "is there a spot where I can edit the global style? Things
-- that every client needs"). Previously these were hardcoded in prompts.py
-- (GLOBAL_STYLE_DOC, BASE_RULES) and required a code change + deploy to
-- touch. Seeded from those same defaults the first time this table is
-- empty -- see prompts.DEFAULT_GLOBAL_STYLE_DOC / DEFAULT_BASE_RULES.
CREATE TABLE IF NOT EXISTS global_style (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    global_style_doc TEXT NOT NULL,
    base_rules TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
'''


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    # Migration: add 'name' column to batches if it doesn't exist yet
    try:
        conn.execute("ALTER TABLE batches ADD COLUMN name TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass  # column already exists

    # Seed global_style with the hardcoded defaults, once, if the table is
    # empty. Import happens here (not at module top) to avoid a circular
    # import, since prompts.py doesn't import db.py.
    row = conn.execute('SELECT id FROM global_style WHERE id = 1').fetchone()
    if not row:
        from prompts import DEFAULT_GLOBAL_STYLE_DOC, DEFAULT_BASE_RULES
        conn.execute(
            'INSERT INTO global_style (id, global_style_doc, base_rules) VALUES (1, ?, ?)',
            (DEFAULT_GLOBAL_STYLE_DOC, DEFAULT_BASE_RULES)
        )
        conn.commit()

    conn.close()


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def close_db(error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()
