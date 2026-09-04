# Production deployment

The frontend is a static bundle. Production serving is **proxy mode**: the bundle
calls a relative `/api/...` URL and a reverse proxy forwards it to Spring Boot.
This keeps the backend URL out of the shipped JS, removes the CORS requirement,
and lets the edge terminate TLS.

## Build

```bash
npm ci                 # reproducible install from package-lock.json
npm run build          # type-checks (vue-tsc -b) + emits dist/ using .env.production
```

`.env.production` sets `VITE_API_BASE=` (empty → relative `/api`). The build is
fully static; everything needed is in `dist/`.

## Serve

1. Copy `dist/` to the web root, e.g. `/var/www/brb-assistant`.
2. Install an nginx config (edit `proxy_pass` to your reachable backend):
   - **Internal / LAN by IP, no TLS:** [`nginx.local.conf`](./nginx.local.conf) —
     plain HTTP on port 80, responds on any IP/host. Use on a trusted segment.
   - **Public / production:** [`nginx.conf`](./nginx.conf) — HTTPS + HSTS; edit
     `server_name` and the TLS cert paths.
3. Reload nginx: `nginx -t && systemctl reload nginx`.

> Plain HTTP (`nginx.local.conf`) sends identity + questions in cleartext — fine on
> a trusted internal network, but see [`SECURITY.md`](../SECURITY.md) before any
> untrusted exposure.

Any reverse proxy works (Caddy, Traefik, an Ingress); nginx is just the reference.
The two non-negotiables in front of the bundle are: **(1)** forward `/api` to the
backend, **(2)** serve `index.html` as the SPA fallback for unknown paths.

## CI/CD (GitLab)

Two pipeline files ship with the repo:

| File | Role | Status |
| --- | --- | --- |
| [`/.gitlab-ci.yml`](../.gitlab-ci.yml) | **CI only** — install → type-check (`vue-tsc -b`) → build. Never touches a server. | **Active** — safe to adopt now |
| [`gitlab-ci.full.yml`](./gitlab-ci.full.yml) | Adds a **manual-gated `deploy:production`** that rsyncs `dist/` to `/var/www/brb-assistant`. | **Reference** — do not activate yet (see gate below) |

### Phase 1 — adopt CI now

`/.gitlab-ci.yml` runs on every push/MR: it caches `~/.npm` (not `node_modules`,
which `npm ci` rebuilds), forwards `node_modules` and `dist/` via **artifacts**,
and gives every MR a green/red status. It assumes a **Docker runner** that can pull
`node:22-bookworm-slim`; for a shell runner, drop the `image:` line and install
Node 22 on the box.

### Phase 2 — enable deploy later

To activate deployment, replace `/.gitlab-ci.yml` with the contents of
`gitlab-ci.full.yml` (or merge its `deploy` stage in). It needs:

- **A shell runner** tagged `brb-deploy` that can reach the web host (has `rsync` + `ssh`).
- **Protected + masked CI/CD variables** (Settings → CI/CD → Variables), exposed
  only on protected refs: `DEPLOY_HOST`, `DEPLOY_USER`, `SSH_PRIVATE_KEY` (File),
  `SSH_KNOWN_HOSTS` (File — `ssh-keyscan $DEPLOY_HOST`), and `ALLOW_PROD_DEPLOY`.
- **A protected `production` environment** with an allowed-deployers / approval list
  (`when: manual` controls *when*, not *who*).
- **nginx pre-configured** per [`nginx.conf`](./nginx.conf) — the pipeline ships
  static files only; it never installs or reloads nginx.

### ⚠️ Deploy is gated OFF on purpose

The `deploy:production` rule requires `$ALLOW_PROD_DEPLOY == "true"`, so the manual
button does **not even appear** until that protected variable is set. Keep it unset
until the two [`SECURITY.md`](../SECURITY.md) release blockers are closed (real
token-based auth; HTTPS/mTLS to the backend). Until then, point the deploy job at an
**internal-only** staging host, not public production.

### Air-gap check (do this first)

`gitlab.brb-tech.uz` is a self-hosted bank instance — the runner may have **no
public egress**. If so, `node:22` (Docker Hub) and `npm ci` (npmjs.org) both fail.
Mirror the image into GitLab's container registry and set `npm_config_registry` to
an internal Nexus/Artifactory proxy. **Verify egress from the runner before the
first run.**

## Run as a service (auto-restart)

Two systemd units serve the **production build** via `vite preview`
(`0.0.0.0:5173`) and restart it on crash. Both use **absolute nvm paths** (systemd
doesn't source nvm) and `--strictPort` (a busy `:5173` fails loudly instead of
silently moving to 5174). Run `npm run build` first — `vite preview` serves `dist/`.

| Unit | File | Reboot survival |
| --- | --- | --- |
| **System** (recommended for a server) | [`brb-frontend.service`](./brb-frontend.service) | ✅ out of the box (`systemctl enable`); needs root to install |
| **User** (no root to install) | [`brb-frontend.user.service`](./brb-frontend.user.service) | ⚠️ only after `sudo loginctl enable-linger ymamajonov` |

> Stop any manually-run dev server on `:5173` **first**, or the unit fails with
> `EADDRINUSE` (because of `--strictPort`): `kill $(ss -tlnp | grep :5173 | grep -oP 'pid=\K[0-9]+')`

**System service (survives reboot, no login needed):**
```bash
sudo cp deploy/brb-frontend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now brb-frontend.service
systemctl status brb-frontend.service
```

**User service (no root to install; the live setup):**
```bash
mkdir -p ~/.config/systemd/user
cp deploy/brb-frontend.user.service ~/.config/systemd/user/brb-frontend.service
systemctl --user daemon-reload
systemctl --user enable --now brb-frontend.service
sudo loginctl enable-linger ymamajonov   # one-time, for boot/logout survival
```

- **Logs:** `journalctl --user -u brb-frontend -f` (drop `--user` for the system unit).
- **Recover after a crash-loop** (5 fails/60s latches `failed`): `systemctl --user reset-failed brb-frontend`.
- **Node version is pinned** to `v22.22.3` in both units — update the `PATH` and `ExecStart` paths if you switch node versions.
- This serves the **production build** via `vite preview` (minified `dist/`, no raw source, no HMR), with the `/api` proxy from `vite.config.ts` (`preview.proxy`). `vite preview` is a lightweight static server — for a hardened production server, **nginx serving `dist/`** is the recommended next step (see [`nginx.local.conf`](./nginx.local.conf); needs root). After any code change, `npm run build` then `systemctl --user restart brb-frontend`.

## Security headers / CSP

`nginx.conf` ships HSTS, `X-Content-Type-Options`, `X-Frame-Options: DENY`,
`Referrer-Policy`, `Permissions-Policy`, and a strict `Content-Security-Policy`.

The CSP allows exactly one inline script — the theme/locale pre-paint block in
`index.html` — via its sha256 hash. **If you edit that inline script, recompute
the hash** or the page will fail to bootstrap:

```bash
node -e 'const fs=require("fs"),c=require("crypto");
const h=fs.readFileSync("dist/index.html","utf8");
const m=h.match(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/);
console.log("sha256-"+c.createHash("sha256").update(m[1]).digest("base64"));'
```

Paste the result into the `script-src` directive.

### Recommended hardening (not yet applied)

- **Self-host the Figtree font** (currently loaded from `fonts.googleapis.com` /
  `fonts.gstatic.com`). Self-hosting removes the third-party requests, the privacy
  leak of user IPs to Google, and lets the CSP drop both Google hosts. After
  self-hosting, tighten to `style-src 'self'` and `font-src 'self'`.
- **Direct mode alternative:** to skip the proxy and call the backend directly,
  set `VITE_API_BASE=https://<backend-host>` in `.env.production`, rebuild, and add
  that origin to `connect-src` in the CSP. The backend must then allow CORS and
  serve HTTPS.
