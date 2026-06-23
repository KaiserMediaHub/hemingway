# Hemingway — LinkedIn Post Writer
Kaiser Media Group

Takes a Degas caption transcript (multiple videos in one file), detects each
video automatically, and writes a tailored LinkedIn post for every one —
trained on that client's voice, style rules, and past writing samples.

---

## What's in this folder

```
hemingway-app/
  server.js          The backend (Express)
  db.js               SQLite database setup
  prompts.js           Writing style logic, transcript parser
  package.json
  .env.example         Template for your environment variables
  public/
    index.html          The entire frontend (login + app)
    assets/kmg-logo.png  Your logo
  data/                 SQLite database lives here (auto-created)
```

---

## Running it locally first (recommended before deploying)

1. Install Node.js 18+ if you don't have it: https://nodejs.org
2. Open a terminal in this folder and run:
   ```
   npm install
   ```
3. Copy `.env.example` to `.env` and fill in:
   - `ANTHROPIC_API_KEY` — your Anthropic API key
   - `TEAM_PASSWORD` — whatever password your team will use to log in
   - `SESSION_SECRET` — any random long string (the .env.example file shows
     a command to generate one)
4. Start it:
   ```
   npm start
   ```
5. Open `http://localhost:3000` in your browser. Log in with your team
   password.

If this works locally, you're ready to deploy.

---

## Deploying to hemingway.kmgtools.us (Railway + Cloudflare)

### Step 1 — Push this folder to GitHub

Railway deploys from a GitHub repo. If you don't already have one for this:

```
cd hemingway-app
git init
git add .
git commit -m "Hemingway v1"
```

Create a new repo on GitHub (can be private), then:

```
git remote add origin https://github.com/YOUR-USERNAME/hemingway-app.git
git branch -M main
git push -u origin main
```

### Step 2 — Create a Railway project

1. Go to https://railway.app and sign up / log in (GitHub login is easiest)
2. Click **New Project** → **Deploy from GitHub repo**
3. Select the `hemingway-app` repo you just pushed
4. Railway will detect it's a Node app and start a build automatically

### Step 3 — Add environment variables in Railway

In your Railway project, go to the service → **Variables** tab, and add:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Anthropic API key |
| `TEAM_PASSWORD` | the password your team will use |
| `SESSION_SECRET` | a random string (generate with the command in `.env.example`) |

Railway sets `PORT` automatically — you don't need to add it.

### Step 4 — Add a persistent volume (important — don't skip this)

The SQLite database needs to survive deploys and restarts.

1. In your Railway service, go to the **Settings** tab
2. Scroll to **Volumes**, click **+ New Volume**
3. Set the mount path to: `/app/data`
4. Save

Without this step, your clients/posts/history will be wiped every time you
redeploy.

### Step 5 — Get your Railway domain

1. In Railway, go to **Settings** → **Networking**
2. Click **Generate Domain** — you'll get something like
   `hemingway-app-production.up.railway.app`
3. Confirm the app loads at that URL and you can log in

### Step 6 — Point hemingway.kmgtools.us to it (Cloudflare)

1. Log into Cloudflare, select the `kmgtools.us` zone
2. Go to **DNS** → **Records** → **Add record**
3. Set:
   - **Type:** CNAME
   - **Name:** `hemingway`
   - **Target:** the Railway domain from Step 5 (e.g.
     `hemingway-app-production.up.railway.app`)
   - **Proxy status:** Proxied (orange cloud) is fine — Cloudflare will
     handle SSL
4. Save

### Step 7 — Add the custom domain in Railway

1. Back in Railway, **Settings** → **Networking** → **Custom Domain**
2. Enter `hemingway.kmgtools.us`
3. Railway will confirm once the CNAME resolves (can take a few minutes
   to an hour)

That's it — `hemingway.kmgtools.us` is live.

---

## Using it day to day

1. Go to `hemingway.kmgtools.us`, log in with the team password
2. Pick a client from the sidebar, or add a new one
3. **Style & Voice tab** — set up once per client:
   - Style rules: plain-language do's and don'ts, one per line
     (e.g. "Don't use the phrase 'last forty years'")
   - Reference copy: upload old posts or writing samples (.txt or .md) so
     Hemingway studies their actual voice
4. **Write Posts tab** — paste the full Degas transcript, pick a writing
   style and length, hit **Write All Posts**
5. Each post can be copied, saved, copied in Hey-Orca-friendly plain text,
   rewritten entirely, or you can click any single paragraph to rewrite
   just that part
6. **History tab** — every batch you've ever generated for that client is
   saved and can be reopened anytime

---

## Updating the app later

Whenever you want to make changes:

```
git add .
git commit -m "describe the change"
git push
```

Railway automatically redeploys on every push to `main`.

---

## Costs to expect

- **Railway:** Usage-based, typically $5–10/month for an app this size
  with light traffic
- **Anthropic API:** Pay-per-use based on how many posts you generate.
  Each post is roughly 1,000–2,500 tokens depending on length. Check
  current pricing at https://www.anthropic.com/pricing
- **Cloudflare/domain:** Whatever you're already paying for kmgtools.us

---

## Security notes

- The Anthropic API key lives only in Railway's environment variables —
  it is never sent to the browser
- The team password gates the whole app behind a login screen
- This is a shared-password setup, not individual accounts. If someone
  leaves the team, change `TEAM_PASSWORD` in Railway and redeploy
