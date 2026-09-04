# CD activation runbook (Phase 4)

Completes the loop: push → CI builds the image → **one click** in GitLab deploys it
live on `:5173` (via [`cutover.sh`](./cutover.sh)). The deploy stage is in
[`gitlab-ci.deploy.yml`](./gitlab-ci.deploy.yml).

> **It stays gated OFF** (`ALLOW_PROD_DEPLOY` unset → no deploy button) until the two
> [`SECURITY.md`](../SECURITY.md) blockers close. This is deliberate — see the gate.

## The runner-identity bridge (the key design)
The cutover is **`ymamajonov`-owned** (it manages `ymamajonov`'s `--user` container
service, rootless podman, and per-user `auth.json`), but the existing runners run as
the `gitlab-runner` *system* user. So the deploy job runs on a **second runner that
runs *as* `ymamajonov`** — no `sudo` (rejected: `ymamajonov` is in group `sudo`, so a
`NOPASSWD` grant into it is root-equivalent on a bank host).

## Activation steps (in order)

1. **Merge MR !9** — `cutover.sh`/`rollback.sh` must be on `main` (the job calls them).
2. **Register the `ymamajonov` user-runner** (no sudo; create a project runner token in the UI first):
   ```bash
   export XDG_RUNTIME_DIR=/run/user/1001
   gitlab-runner register --non-interactive --config ~/.gitlab-runner/config.toml \
     --url https://gitlab.brb-tech.uz/ --token <PROJECT_RUNNER_TOKEN> \
     --executor shell --description 'brb-deploy (user=ymamajonov)' \
     --tag-list llm-brb-tech-deploy-user --run-untagged=false --access-level=ref_protected --locked=true
   ```
   Keep it alive (linger is already on) via a `--user` unit:
   ```bash
   # ~/.config/systemd/user/gitlab-runner.service → ExecStart=/usr/bin/gitlab-runner run \
   #   --config %h/.gitlab-runner/config.toml --working-directory %h ; Restart=always
   systemctl --user daemon-reload && systemctl --user enable --now gitlab-runner.service
   ```
   Confirm a job tagged `llm-brb-tech-deploy-user` prints `id -un` = `ymamajonov`. Mark it **Protected** in the UI.
3. **Pre-seed the rollback target** (one-time — the live state file uses a different key than MR !9 reads):
   ```bash
   F=~/.local/state/brb-cutover/state.env
   printf 'previous_image_digest=%s\n' "$(grep -E '^image_repo_digest=' "$F" | tail -1 | cut -d= -f2-)" >> "$F"
   ```
   (The deploy job's `before_script` **aborts** if this is missing, so it can't ship a broken rollback target.)
4. **GitLab governance:** make `production` a **PROTECTED environment** with an approver list; keep `main`
   protected + MR-only + CODEOWNERS; the deploy runner Protected.
5. **Add the deploy stage:** merge [`gitlab-ci.deploy.yml`](./gitlab-ci.deploy.yml) into `.gitlab-ci.yml`
   (add `- deploy` to `stages:` and the `deploy:production` job).
6. **Set CI/CD variables** (Protected + Masked, protected refs only): `API_UPSTREAM` (default
   `http://10.10.50.9:8080`). Leave **`ALLOW_PROD_DEPLOY` UNSET**. Do **not** define `CI_REGISTRY_*` (auto-injected).
7. **Close both `SECURITY.md` blockers** (token-derived identity; HTTPS/mTLS to the backend) and get sign-off.
8. **Go live:** set `ALLOW_PROD_DEPLOY=true` (protected). The manual **`deploy:production`** button now appears on
   `main` pipelines — an approver clicks it once to cut over to the freshly-built image.
9. Retire the old system deploy runner (`llm-brb-tech-deploy`, uid 998) so a job can't land on the wrong identity.

## The gate (three independent locks)
- **WHEN** — `when: manual` (a human clicks).
- **WHO** — the protected `production` environment's approver list.
- **SIGN-OFF** — `ALLOW_PROD_DEPLOY == "true"`; while unset the rule is false and the button never appears.

## Caveats (read before activating)
- **No tests gate this.** CI only type-checks/builds + a `/healthz` smoke test (backend-independent). Any image that
  boots nginx is promotable with **no behavioral verification** — which is exactly why deploy is one-click MANUAL.
- **`SECURITY.md` blockers open** — client-asserted/spoofable identity + plaintext HTTP backend. Keep CD gated off
  until they close.
- **`0.0.0.0:5173` exposure** — the live container binds all interfaces (for LAN access), so the vulnerable surface is
  reachable on the whole network, not just behind the TLS nginx. Consider reverting to `127.0.0.1` until the blockers
  close (a one-line `cutover.sh` change) and accessing only via the domain.
- **First-deploy rollback** needs the pre-seed (step 3); after one CD cutover the state file self-populates.
- **`cutover.sh`'s built-in EXIT trap still tries to restart the retired `vite`** — harmless but ineffective; the deploy
  job drives the correct `rollback.sh --to-previous` afterward. (Cleaner fix: add `--no-auto-rollback` to `cutover.sh`.)
- **Single host = SPOF** + a ~1–3s swap window (not zero-downtime). HA needs a second host + external LB.
