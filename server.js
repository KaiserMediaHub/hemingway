require('dotenv').config();
const express = require('express');
const cookieSession = require('cookie-session');
const multer = require('multer');
const path = require('path');
const https = require('https');
const db = require('./db');
const { buildSystemPrompt, buildUserPrompt, splitTranscript } = require('./prompts');

const app = express();
app.set('trust proxy', 1);
const PORT = process.env.PORT || 3000;
const TEAM_PASSWORD = process.env.TEAM_PASSWORD || 'changeme';
const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY || '';
const SESSION_SECRET = process.env.SESSION_SECRET || 'hemingway-kmg-secret-change-this';

app.use(express.json({ limit: '10mb' }));
app.use(express.static(path.join(__dirname, 'public')));

app.use(cookieSession({
  name: 'hemingway-session',
  secret: SESSION_SECRET,
  maxAge: 30 * 24 * 60 * 60 * 1000 // 30 days
}));

const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 5 * 1024 * 1024 } });

// ---------- Auth middleware ----------
function requireAuth(req, res, next) {
  if (req.session && req.session.loggedIn) return next();
  return res.status(401).json({ error: { message: 'Not authenticated' } });
}

// ---------- Auth routes ----------
app.post('/api/login', (req, res) => {
  const { password } = req.body;
  if (password === TEAM_PASSWORD) {
    req.session.loggedIn = true;
    return res.json({ ok: true });
  }
  return res.status(401).json({ error: { message: 'Incorrect password' } });
});

app.post('/api/logout', (req, res) => {
  req.session = null;
  res.json({ ok: true });
});

app.get('/api/session', (req, res) => {
  res.json({ loggedIn: !!(req.session && req.session.loggedIn) });
});

// ---------- Client routes ----------
app.get('/api/clients', requireAuth, (req, res) => {
  const clients = db.prepare('SELECT id, name, style_rules, created_at FROM clients ORDER BY name ASC').all();
  res.json(clients);
});

app.post('/api/clients', requireAuth, (req, res) => {
  const { name } = req.body;
  if (!name || !name.trim()) return res.status(400).json({ error: { message: 'Client name required' } });
  const stmt = db.prepare('INSERT INTO clients (name) VALUES (?)');
  const info = stmt.run(name.trim());
  res.json({ id: info.lastInsertRowid, name: name.trim(), style_rules: '' });
});

app.delete('/api/clients/:id', requireAuth, (req, res) => {
  db.prepare('DELETE FROM clients WHERE id = ?').run(req.params.id);
  res.json({ ok: true });
});

app.put('/api/clients/:id/style-rules', requireAuth, (req, res) => {
  const { style_rules } = req.body;
  db.prepare('UPDATE clients SET style_rules = ? WHERE id = ?').run(style_rules || '', req.params.id);
  res.json({ ok: true });
});

// ---------- Style docs (reference copy) ----------
app.get('/api/clients/:id/docs', requireAuth, (req, res) => {
  const docs = db.prepare('SELECT id, filename, created_at, length(content) as size FROM style_docs WHERE client_id = ? ORDER BY created_at DESC').all(req.params.id);
  res.json(docs);
});

app.post('/api/clients/:id/docs', requireAuth, upload.array('files', 10), (req, res) => {
  const clientId = req.params.id;
  const stmt = db.prepare('INSERT INTO style_docs (client_id, filename, content) VALUES (?, ?, ?)');
  const inserted = [];
  for (const file of (req.files || [])) {
    const content = file.buffer.toString('utf-8');
    const info = stmt.run(clientId, file.originalname, content);
    inserted.push({ id: info.lastInsertRowid, filename: file.originalname });
  }
  res.json({ ok: true, inserted });
});

app.delete('/api/docs/:id', requireAuth, (req, res) => {
  db.prepare('DELETE FROM style_docs WHERE id = ?').run(req.params.id);
  res.json({ ok: true });
});

// ---------- Batches / history ----------
app.get('/api/clients/:id/batches', requireAuth, (req, res) => {
  const batches = db.prepare('SELECT id, style, length, context, created_at FROM batches WHERE client_id = ? ORDER BY created_at DESC').all(req.params.id);
  res.json(batches);
});

app.get('/api/batches/:id', requireAuth, (req, res) => {
  const batch = db.prepare('SELECT id, client_id, transcript_raw, style, length, context, created_at FROM batches WHERE id = ?').get(req.params.id);
  if (!batch) return res.status(404).json({ error: { message: 'Batch not found.' } });
  res.json(batch);
});

app.get('/api/batches/:id/posts', requireAuth, (req, res) => {
  const posts = db.prepare('SELECT id, title, body, section_body FROM posts WHERE batch_id = ? ORDER BY id ASC').all(req.params.id);
  res.json(posts);
});

app.delete('/api/batches/:id', requireAuth, (req, res) => {
  db.prepare('DELETE FROM batches WHERE id = ?').run(req.params.id);
  res.json({ ok: true });
});

// ---------- Anthropic proxy ----------
function callAnthropic(payload) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(payload);
    const options = {
      hostname: 'api.anthropic.com',
      path: '/v1/messages',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'Content-Length': Buffer.byteLength(data)
      }
    };
    const req = https.request(options, (apiRes) => {
      let body = '';
      apiRes.on('data', chunk => body += chunk);
      apiRes.on('end', () => {
        try {
          const parsed = JSON.parse(body);
          if (apiRes.statusCode >= 400) {
            return reject(new Error(parsed.error?.message || 'Anthropic API error'));
          }
          resolve(parsed);
        } catch (e) {
          reject(new Error('Failed to parse Anthropic response'));
        }
      });
    });
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

async function writePostForSection(title, sectionBody, fullCorpus, style, length, clientRules, styleDocsText, batchContext) {
  const systemPrompt = buildSystemPrompt(style, clientRules);
  const userPrompt = buildUserPrompt(title, sectionBody, fullCorpus, length, styleDocsText, batchContext);

  const result = await callAnthropic({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 1200,
    system: systemPrompt,
    messages: [{ role: 'user', content: userPrompt }]
  });

  const textBlock = (result.content || []).find(b => b.type === 'text');
  return textBlock ? textBlock.text : '';
}

// Generate posts for an entire transcript, save as a batch
app.post('/api/generate', requireAuth, async (req, res) => {
  const { clientId, transcript, style, length, context } = req.body;

  if (!ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: { message: 'Server is missing ANTHROPIC_API_KEY. Contact the admin.' } });
  }
  if (!clientId || !transcript || !style || !length) {
    return res.status(400).json({ error: { message: 'Missing required fields.' } });
  }

  const client = db.prepare('SELECT * FROM clients WHERE id = ?').get(clientId);
  if (!client) return res.status(404).json({ error: { message: 'Client not found.' } });

  const sections = splitTranscript(transcript);
  if (sections.length === 0) {
    return res.status(400).json({ error: { message: 'No video sections detected. Make sure this is a Degas transcript with VIDEO: headers.' } });
  }

  const docs = db.prepare('SELECT content FROM style_docs WHERE client_id = ?').all(clientId);
  const styleDocsText = docs.map(d => d.content).join('\n\n---\n\n');
  const batchContext = context || '';

  const batchStmt = db.prepare('INSERT INTO batches (client_id, transcript_raw, style, length, context) VALUES (?, ?, ?, ?, ?)');
  const batchInfo = batchStmt.run(clientId, transcript, style, length, batchContext);
  const batchId = batchInfo.lastInsertRowid;

  const postStmt = db.prepare('INSERT INTO posts (batch_id, title, body, section_body) VALUES (?, ?, ?, ?)');

  const results = [];
  for (const sec of sections) {
    try {
      const post = await writePostForSection(sec.title, sec.body, transcript, style, length, client.style_rules, styleDocsText, batchContext);
      const info = postStmt.run(batchId, sec.title, post, sec.body);
      results.push({ id: info.lastInsertRowid, title: sec.title, body: post, error: null });
    } catch (err) {
      results.push({ id: null, title: sec.title, body: '', error: err.message });
    }
  }

  res.json({ batchId, posts: results });
});

// Regenerate / rewrite a single post
app.post('/api/posts/:id/rewrite', requireAuth, async (req, res) => {
  if (!ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: { message: 'Server is missing ANTHROPIC_API_KEY.' } });
  }

  const post = db.prepare('SELECT * FROM posts WHERE id = ?').get(req.params.id);
  if (!post) return res.status(404).json({ error: { message: 'Post not found.' } });

  const batch = db.prepare('SELECT * FROM batches WHERE id = ?').get(post.batch_id);
  const client = db.prepare('SELECT * FROM clients WHERE id = ?').get(batch.client_id);
  const docs = db.prepare('SELECT content FROM style_docs WHERE client_id = ?').all(client.id);
  const styleDocsText = docs.map(d => d.content).join('\n\n---\n\n');

  // Allow instruction override for this rewrite (e.g. "make it shorter")
  const extraInstruction = req.body?.instruction || '';
  let clientRules = client.style_rules || '';
  if (extraInstruction.trim()) {
    clientRules += `\n\nFor this specific rewrite, also follow this instruction: ${extraInstruction.trim()}`;
  }

  try {
    const newBody = await writePostForSection(post.title, post.section_body, batch.transcript_raw, batch.style, batch.length, clientRules, styleDocsText, batch.context);
    db.prepare('UPDATE posts SET body = ? WHERE id = ?').run(newBody, post.id);
    res.json({ id: post.id, title: post.title, body: newBody });
  } catch (err) {
    res.status(500).json({ error: { message: err.message } });
  }
});

// Regenerate a specific paragraph within a post
app.post('/api/posts/:id/rewrite-paragraph', requireAuth, async (req, res) => {
  if (!ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: { message: 'Server is missing ANTHROPIC_API_KEY.' } });
  }

  const { paragraphIndex, instruction } = req.body;
  const post = db.prepare('SELECT * FROM posts WHERE id = ?').get(req.params.id);
  if (!post) return res.status(404).json({ error: { message: 'Post not found.' } });

  const batch = db.prepare('SELECT * FROM batches WHERE id = ?').get(post.batch_id);
  const client = db.prepare('SELECT * FROM clients WHERE id = ?').get(batch.client_id);

  const paragraphs = post.body.split(/\n\n+/);
  if (paragraphIndex < 0 || paragraphIndex >= paragraphs.length) {
    return res.status(400).json({ error: { message: 'Invalid paragraph index.' } });
  }

  const targetParagraph = paragraphs[paragraphIndex];
  const systemPrompt = buildSystemPrompt(batch.style, client.style_rules) +
    '\n\nYou are revising ONE paragraph of an existing LinkedIn post. Keep it consistent with the rest of the post in tone and voice. Output ONLY the rewritten paragraph text, nothing else.';

  const userPrompt = `Full post for context:\n\n${post.body}\n\n---\n\nThe paragraph to rewrite:\n\n"${targetParagraph}"\n\n${instruction ? 'Instruction: ' + instruction : 'Rewrite this paragraph to be stronger, while keeping the same core point.'}\n\nOutput only the new paragraph text.`;

  try {
    const result = await callAnthropic({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 400,
      system: systemPrompt,
      messages: [{ role: 'user', content: userPrompt }]
    });
    const textBlock = (result.content || []).find(b => b.type === 'text');
    const newParagraph = textBlock ? textBlock.text.trim() : targetParagraph;

    paragraphs[paragraphIndex] = newParagraph;
    const newBody = paragraphs.join('\n\n');
    db.prepare('UPDATE posts SET body = ? WHERE id = ?').run(newBody, post.id);

    res.json({ id: post.id, body: newBody, paragraph: newParagraph });
  } catch (err) {
    res.status(500).json({ error: { message: err.message } });
  }
});

app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`Hemingway running on port ${PORT}`);
  if (!ANTHROPIC_API_KEY) {
    console.warn('WARNING: ANTHROPIC_API_KEY is not set. Generation will fail until it is configured.');
  }
});
