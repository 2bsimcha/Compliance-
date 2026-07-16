# Deploying to a live website (Render)

This app is a live Python server (FastAPI + a database), not a static site — so it needs
a host that runs a persistent process. This guide uses **Render**; the same app runs on
Railway, Fly.io, or your own server with equivalent settings.

Your existing marketing site can stay where it is — put this app on a **subdomain**
(e.g. `app.yourdomain.com` or `compliance.yourdomain.com`).

---

## What's already set up for deployment

- **`render.yaml`** — a Render Blueprint: build command, start command, health check,
  a persistent disk for the SQLite database, and all the environment variables.
- **Login gate** — the whole instance sits behind a password (`APP_PASSWORD`). Set that
  variable and the site is private; leave it unset and it's open (local dev only).
- **`/healthz`** — a public health-check endpoint Render pings to know the app is up.

---

## One-time deploy

**Prerequisites:** a GitHub account with this repo, a free Render account
(https://render.com), and a domain you control.

1. **Get the code onto a branch Render can deploy.** Render deploys from a branch of your
   GitHub repo (commonly `main`). Merge this work there, or point Render at this branch.

2. **Create the service from the Blueprint.**
   Render Dashboard → **New** → **Blueprint** → connect your GitHub repo. Render reads
   `render.yaml` and proposes the `cpsc-compliance` web service. Click **Apply**.

3. **Set the secret environment variables** (Render prompts for the ones marked
   `sync: false`):
   - `APP_PASSWORD` — **required.** The password you'll use to log in. Pick a strong one.
   - `ANTHROPIC_API_KEY` — optional. Add it to enable Claude-backed intake extraction;
     without it, extraction falls back to keyword heuristics. (Get a key at
     https://console.anthropic.com.)

   `SESSION_SECRET` is generated automatically; `APP_USERNAME` defaults to `admin`.

4. **Deploy.** The first build installs dependencies and starts the app (a few minutes).
   When it's live, open the `…onrender.com` URL, sign in with `admin` + your
   `APP_PASSWORD`, and confirm it works. The eCFR "current as of" banner should now load
   real data (outbound internet works on Render, unlike a locked-down sandbox).

5. **Point your domain at it.**
   In the service's **Settings → Custom Domains**, add `app.yourdomain.com`. Render shows
   a target hostname — create a **CNAME** record for `app` pointing to it in your DNS
   provider. Render provisions a free HTTPS certificate automatically once DNS resolves.

Done — the app is live at `https://app.yourdomain.com`, private behind your password.

---

## Important notes

- **Data persistence / pricing.** SQLite lives on the mounted disk (`/var/data`), which
  requires a **paid** Render instance. On the **free** web tier there is no persistent
  disk, so the database resets on every deploy. Two options:
  - Pay for the Starter instance (keeps the disk), **or**
  - Switch to a managed **Postgres** (Render offers one): create a Postgres instance,
    then change `DATABASE_URL` to the connection string it gives you (starts with
    `postgresql://`) and remove the `disk:` block from `render.yaml`. The app already
    supports this — it's a one-variable change (`app/database.py`). Add `psycopg[binary]`
    to `requirements.txt` for the Postgres driver.

- **Keep a single instance while on SQLite.** SQLite is a single-writer file database;
  don't scale to multiple instances until you've moved to Postgres.

- **Rotating the password.** Change `APP_PASSWORD` in the Render dashboard and redeploy.
  All existing sessions stay valid until they're cleared; change `SESSION_SECRET` too if
  you want to force everyone to re-login.

- **This is single-tenant.** One password protects one shared portfolio — everyone who
  logs in sees the same products. That's the right scope for a private tool or early
  access. True per-customer accounts (each company sees only its own products) is a
  larger feature to add when you productize.

---

## Alternatives

- **Railway / Fly.io** — same shape: connect the repo, set the start command
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, add the same env vars, attach a
  volume or Postgres, point DNS. Fly uses a `Dockerfile`; a minimal one:

  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
  ```

- **Your own VPS** — run the same `uvicorn` command under a process manager (systemd),
  put nginx in front as a reverse proxy, and use certbot for HTTPS. More control, more
  setup.
