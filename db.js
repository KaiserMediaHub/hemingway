// Uses Node's built-in SQLite (node:sqlite) — no native compilation required.
// Available in Node 22.5+ (stable enough for this use, may show an
// "experimental" warning in the console — that's expected and harmless).
const { DatabaseSync } = require('node:sqlite');
const path = require('path');
const fs = require('fs');

const DATA_DIR = path.join(__dirname, 'data');
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

const sqlite = new DatabaseSync(path.join(DATA_DIR, 'hemingway.db'));
sqlite.exec('PRAGMA journal_mode = WAL;');

sqlite.exec(`
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
`);

// Migration: add 'context' column to batches if it doesn't exist yet
// (safe to run every startup — silently does nothing if already added)
try {
  sqlite.exec(`ALTER TABLE batches ADD COLUMN context TEXT DEFAULT '';`);
} catch (e) {
  // column already exists — ignore
}

// Thin wrapper so the rest of the app can use the same
// .prepare(sql).run()/.get()/.all() pattern regardless of driver.
const db = {
  prepare(sql) {
    const stmt = sqlite.prepare(sql);
    return {
      run: (...args) => stmt.run(...args),
      get: (...args) => stmt.get(...args),
      all: (...args) => stmt.all(...args)
    };
  },
  pragma() {
    // no-op: handled directly above via sqlite.exec()
  }
};

module.exports = db;
