# Cutover: swap `vite preview` on :5173 for the container

[`cutover.sh`](./cutover.sh) makes a CI-built image the live `:5173` frontend, with a
health gate and automatic rollback. [`rollback.sh`](./rollback.sh) restores a
known-good state. Both are **run-as-ymamajonov** and **do not touch the DevOps host
nginx** (it keeps proxying the public domain → `localhost:5173`).

> ⚠️ These scripts change what serves live traffic on the single host. Run them
> yourself, in a maintenance window — they are **not** run by CI yet (that is Phase 4).

## Identity model — run-as-ymamajonov
`ymamajonov` owns the live `vite` `--user` service **and** has working rootless
podman, so one user retires `vite` and runs the container — no cross-user `sudo`.
Verified on this host: `subuid/subgid 165536:65536`, linger on, `podman info →
Rootless:true`.

## One-time prerequisites
1. **Rootless podman for ymamajonov** — already done (verified). If ever missing after
   a rebuild: `sudo usermod --add-subuids 165536-231071 --add-subgids 165536-231071 ymamajonov && sudo loginctl enable-linger ymamajonov && podman system migrate`.
2. **Registry login** — log into the **real** registry host (see #3). A `read_registry`
   GitLab deploy token *should* work, but the token's real **username is not the "Name"
   you typed** — GitLab shows it (often `gitlab+deploy-token-N`) at creation. If it 403s,
   use your account / a PAT, or `podman login` manually then run `cutover.sh --no-login`
   (it reuses `auth.json`). Creds go via `--password-stdin`, never on argv/logs.
3. **The registry host is `registry.brb-tech.uz`** — NOT `gitlab.brb-tech.uz` (that host's
   `/v2/` is the *dependency proxy*; pulling a project image there 404s) and NOT
   `registry.gitlab.brb-tech.uz` (doesn't resolve). Find the exact host under **Deploy →
   Container Registry** (it shows the full image path). `cutover.sh` DNS-preflights whatever
   host is in `--image` and fails early if it doesn't resolve.
4. **An image in the registry** — built + pushed by CI by an immutable `@sha256`
   digest or full-40-char-SHA tag. `curl` + `ss` (iproute2) must be present (they are).

## Run it
```bash
export XDG_RUNTIME_DIR=/run/user/1001
export REGISTRY_USER=<deploy-token-user>
export REGISTRY_PASSWORD=<deploy-token-secret>

deploy/cutover.sh \
  --image registry.brb-tech.uz/y.mamajonov/brbtechllm_frontend@sha256:<digest> \
  --api-upstream http://192.168.77.96:8080
# or, after a manual `podman login registry.brb-tech.uz`, add --no-login (no creds needed)
```
Flow: preflight → login → pull → resolve **repo digest** → start a **separate
staging container** on `:5174` and `/healthz`-gate it (live `:5173` untouched) → stop
`vite` → generate a systemd `--user` unit and start it as the **only** binder of
`:5173` → `/healthz`-gate → disable `vite`. Any failure after `vite` is stopped
**auto-rolls back to `vite`**. The container gets crash auto-restart + reboot survival
via the generated unit (linger on).

### Rollback
```bash
deploy/rollback.sh --to-vite        # safe floor: back to the vite service
deploy/rollback.sh --to-previous    # re-bind the previous image digest (needs API_UPSTREAM exported)
```

## Caveats (honest)
- **Brief swap window (~1–3s), not true zero-downtime.** Host nginx is fixed on
  `:5173` and `vite` uses `--strictPort`, so two processes can't hold `:5173` at once.
  Minimized via the staging pre-gate; a bad image fails staging with **zero** downtime.
- **True zero-downtime** would need the DevOps host nginx to become the switch (stable
  local upstreams + `nginx -s reload` to flip) — a DevOps change, out of scope here.
- **`/api` 502s until the backend is reachable** (`192.168.77.96:8080` is unreachable
  from this host). The health gate tests `/healthz` only; the SPA is fine.
- **Empty `API_UPSTREAM` fails closed at deploy** — nginx renders `proxy_pass
  ${API_UPSTREAM};`, so an empty value stops the **whole** container from starting (not
  graceful per-`/api`). Both scripts refuse an empty upstream, so that state never ships.
- **Single-host SPOF** — the unit gives crash + reboot recovery, but a host failure
  takes the site down. HA needs a second host + external LB (not addressed).
- Image is pinned by **repo digest** (re-pullable), so `podman image prune` can't break
  the next reboot.

## Status / validation
Authored from a verified design (5-agent workflow + adversarial review); fixes applied:
repo-digest (not local Id), registry-DNS preflight, separate staging container,
single systemd binder (no double-bind), `wait_port_free` with the holder PID. Both
scripts pass `bash -n`. **Not yet executed on the host** — review, then run in a window.
