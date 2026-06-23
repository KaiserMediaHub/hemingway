# Deploying Hemingway to Hetzner

**Target:** `hemingway.kmgtools.us` → `178.104.152.111`  
**Stack:** Flask + Gunicorn + nginx + Let's Encrypt

---

## Step 1 — Push to GitHub

**1a. Create a new repo on GitHub**

Go to [github.com/new](https://github.com/new), give it a name (e.g. `hemingway`), set it to Private, and click **Create repository**. Don't add a README or .gitignore — keep it empty.

**1b. Initialise git on your local machine**

Open a terminal in the Hemingway folder and run:

```bash
git init
git add .
git commit -m "Hemingway v2 — Flask rebuild"
```

**1c. Connect to GitHub and push**

Copy the repo URL from GitHub (looks like `https://github.com/YOUR-USERNAME/hemingway.git`), then run:

```bash
git remote add origin https://github.com/YOUR-USERNAME/hemingway.git
git branch -M main
git push -u origin main
```

Refresh the GitHub page — you should see all the files there.

---

## Step 2 — SSH into the server

```bash
ssh root@178.104.152.111
```

---

## Step 3 — Clone the repo

```bash
git clone https://github.com/YOUR-USERNAME/hemingway.git /var/www/hemingway
cd /var/www/hemingway
```

---

## Step 4 — Set up Python environment

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install gunicorn
```

---

## Step 5 — Create the .env file on the server

```bash
nano /var/www/hemingway/.env
```

Paste this and fill in the values:

```
ANTHROPIC_API_KEY=your-anthropic-api-key-here
TEAM_PASSWORD=your-team-password-here
SESSION_SECRET=some-long-random-string-here
PORT=3000
```

To generate a good SESSION_SECRET, run:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Save and close (`Ctrl+O`, `Enter`, `Ctrl+X`).

---

## Step 6 — Test it manually

Make sure it starts cleanly before wiring up the service:

```bash
cd /var/www/hemingway
.venv/bin/python app.py
```

You should see `Hemingway running on port 3000`. Press `Ctrl+C` to stop it.

---

## Step 7 — Create a systemd service

This keeps the app running in the background and auto-starts it on reboot.

```bash
nano /etc/systemd/system/hemingway.service
```

Paste this exactly:

```ini
[Unit]
Description=Hemingway — LinkedIn Post Writer
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/hemingway
EnvironmentFile=/var/www/hemingway/.env
ExecStart=/var/www/hemingway/.venv/bin/gunicorn \
    --workers 2 \
    --bind 127.0.0.1:3000 \
    --timeout 120 \
    app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The `--timeout 120` is important — generating posts across a long transcript can take 60+ seconds.

Enable and start it:

```bash
systemctl daemon-reload
systemctl enable hemingway
systemctl start hemingway
```

Check it's running:

```bash
systemctl status hemingway
```

You should see `active (running)`. If not, check logs with `journalctl -u hemingway -n 50`.

Fix the file permissions so www-data can read the .env and write to data/:

```bash
chown -R www-data:www-data /var/www/hemingway
chmod 640 /var/www/hemingway/.env
```

Restart after the chown:

```bash
systemctl restart hemingway
systemctl status hemingway
```

---

## Step 8 — Configure nginx

```bash
nano /etc/nginx/sites-available/hemingway
```

Paste this:

```nginx
server {
    listen 80;
    server_name hemingway.kmgtools.us;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;
    }
}
```

Enable the site:

```bash
ln -s /etc/nginx/sites-available/hemingway /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
```

At this point `http://hemingway.kmgtools.us` should load (once DNS is pointed — see next step).

---

## Step 9 — Point DNS in Cloudflare

1. Log into Cloudflare, select the `kmgtools.us` zone
2. Go to **DNS → Records → Add record**
3. Set:
   - **Type:** A
   - **Name:** `hemingway`
   - **IPv4 address:** `178.104.152.111`
   - **Proxy status:** DNS only (grey cloud) for now — switch to Proxied after SSL is working
4. Save

DNS propagation is usually instant with Cloudflare.

---

## Step 10 — SSL with Let's Encrypt

If certbot isn't installed yet:

```bash
apt install certbot python3-certbot-nginx -y
```

Then run:

```bash
certbot --nginx -d hemingway.kmgtools.us
```

Follow the prompts. Certbot will automatically update your nginx config with SSL and set up auto-renewal.

Once done, go back to Cloudflare and switch the proxy status to **Proxied** (orange cloud) — Cloudflare will handle the CDN layer on top.

---

## Updating the app later

Whenever you push changes:

```bash
ssh root@178.104.152.111
cd /var/www/hemingway
git pull
.venv/bin/pip install -r requirements.txt  # only needed if requirements changed
systemctl restart hemingway
```

That's it — `hemingway.kmgtools.us` is live.

---

## Troubleshooting

| Problem | Command to run |
|---|---|
| App not starting | `journalctl -u hemingway -n 50` |
| nginx errors | `nginx -t` then `journalctl -u nginx -n 20` |
| 502 Bad Gateway | App isn't running — check `systemctl status hemingway` |
| SSL not renewing | `certbot renew --dry-run` |
