# Enterprise CI/CD & Deployment Architecture

Reference architecture and roadmap to take the BRB‑Tech Assistant frontend from its
current state (one host, `vite preview`, no tests, no runner) to a genuinely
enterprise‑grade, senior‑built delivery pipeline — right‑sized for a single
self‑hosted bank server with a clear, non‑cargo‑culted growth path.

> **Status (honest):** the *pipeline* described here is enterprise‑grade. The
> *application* is **not enterprise‑ready yet**, and cannot be made so by the
> frontend team alone. Two blockers are **backend/platform deliverables** — see
> [Must‑fix blockers](#must-fix-blockers). A signed, scanned, well‑tested image of
> a client‑spoofable, cleartext‑PII app is just an insecure app with excellent
> provenance.

---

## 1. The two release‑gating blockers (read first)

| # | Blocker | Evidence | Owner |
|---|---------|----------|-------|
| 1 | **No real auth — identity is client‑asserted.** The request body carries a user‑editable `actorType`/`roles`/`department`; the identity bar lets anyone select `RAG_ADMIN`; the token is a fake `demo.<ts>`. If the backend trusts the body → privilege escalation / IDOR. | `src/views/ChatView.vue` (spreads identity into the body), `src/composables/useAuth.ts` (mints demo token) | **Frontend** sends a real OIDC Bearer token and stops sending identity; **Backend** derives identity from the verified token and ignores the body. *Enforced only when the backend changes.* |
| 2 | **PII crosses the wire in plaintext HTTP.** `proxy_pass http://10.10.50.9:8080`; email/employee‑id/roles/questions are unencrypted on the proxy→backend hop. Edge TLS does not cover it. | `deploy/nginx.conf`, `deploy/nginx.local.conf` | **Backend/platform**: terminate TLS on the backend (or sidecar), use `https` + `proxy_ssl_verify` + pinned bank CA; **mTLS** for a bank. |

**These are the real critical path.** Name the backend owner and agree the
interface contract (OIDC issuer, claims→identity mapping, token audience; backend
CA + cert SAN + mTLS identity) before the pipeline work is meaningful. The prod
deploy gate (`ALLOW_PROD_DEPLOY`) must stay closed until the **backend** signs off.

---

## 2. Reference architecture

**Principle: build once, promote the *same* immutable digest, the prod host only
*runs* artifacts — it never builds.**

```
commit ─▶ MR pipeline
  validate   lint · format · type-check · secret-scan · npm audit · lockfile-clean
  test       vitest unit/component + coverage gate
  build-image ONE multi-stage image, base pinned by @sha256, tagged by commit SHA
              → push to GitLab Container Registry, emit IMAGE_DIGEST
  scan       Trivy image scan by DIGEST (HIGH/CRITICAL = block) + SBOM (CycloneDX)
  [sign]     (later phase) cosign sign + attest by digest
  deploy-staging   pull by DIGEST → blue/green swap → /healthz gate
  e2e        Playwright @smoke against the staging image (/api mocked)
  promote-prod     MANUAL + protected env + approval; pull the SAME digest;
                   blue/green flip + post-flip smoke + automatic rollback
```

**Why one image serves all environments:** `.env.production` has `VITE_API_BASE=""`
(proxy mode → relative `/api`), so the backend URL is **not** baked into the JS —
it lives only in nginx's upstream, injected at **runtime** via `envsubst`. The only
per‑environment difference is the `API_UPSTREAM` env var, never a rebuilt artifact.
Never reintroduce a baked per‑env `VITE_API_BASE`.

**Artifact identity:** the canonical, immutable identity is the **full 40‑char
commit‑SHA tag** (≡ the manifest `@sha256` digest captured at build time). Promotion
and rollback **only** reference a digest/SHA. Release builds add a `vX.Y.Z` label on
the *same* digest. No moving `latest`/`vX` tags. Enable **protected/immutable tags**
in the registry so SHA and release tags cannot be overwritten.

---

## 3. Deployment model (single host, today)

- **Runtime:** rootless **Podman** (least privilege; avoids the docker‑socket =
  host‑root foot‑gun). Rootful Docker acceptable if Podman is impractical.
- **Edge:** the existing **host nginx** keeps terminating TLS for the public domain
  and becomes the **blue/green switch**. It forwards to the *active* container
  (`:8080` blue / `:8081` green). The container's **own** nginx does SPA fallback +
  `/api` proxy + security headers. The host port flips from today's `vite preview`
  on `:5173` to the container.
- **Zero‑downtime blue/green (two slots on one box):**
  1. `podman pull <repo>@<digest>` (+ `cosign verify` once signing lands).
  2. Start the **new** color on the idle port with `API_UPSTREAM` set.
  3. Wait for **`/healthz`** on the new container — a static 200, **backend‑independent**
     (added in the container nginx; the app has no such endpoint today).
  4. Run a Playwright `@smoke` subset against the new color directly.
  5. Atomically repoint the host‑nginx upstream `include` to the new color → `nginx -s reload` (graceful drain).
  6. Re‑verify `/healthz` on the public path.
  7. **Any failure in 3–6 → automatic, recorded revert** to the previous color (kept running) — instant rollback.
- **Rollback anytime** = redeploy the previous immutable digest (flip the upstream), recorded as its own GitLab Deployment.
- **Health:** `/healthz` (liveness+readiness, no backend dependency) + optional `/version` returning the deployed SHA.

---

## 4. Pipeline (`.gitlab-ci.yml`) outline

Stages: `validate → test → build-image → scan → [sign] → deploy-staging → e2e → promote-prod`.

- **Runner split:** a `brb-build` runner (build/test/scan; **no prod credentials**)
  and a `brb-deploy` **shell** runner (protected refs only, reaches the web host).
  Project/group‑scoped, never the shared instance runner.
- **validate (blocking on MR):** `npm ci` then `git diff --exit-code package-lock.json`
  (lock drift = fail); `prettier --check`; `eslint --max-warnings 0` (incl. a
  `v-html` ban); `vue-tsc -b` + type‑check the tests; Secret‑Detection + SAST;
  `npm audit --audit-level=high --omit=dev` (against the Nexus advisory mirror; a
  dated, AppSec‑approved allowlist file only — never `|| true`).
- **test (blocking):** `vitest run --coverage` (JUnit + cobertura to the MR). Global
  coverage floor starts at 0 and **ratchets**; the teeth are **per‑file** floors on
  the files with real logic (`src/api.ts`, `useAuth`, router guard, `PipelineResult`).
- **build-image:** Buildah/buildx, digest‑pinned bases, proxy‑mode bundle, push by
  SHA, emit `IMAGE_DIGEST` (dotenv) consumed by every downstream stage.
- **scan:** Trivy by **digest**, blocking HIGH/CRITICAL, air‑gapped DB, **fail‑closed**
  on a DB/mirror outage; retain one CycloneDX SBOM per release.
- **deploy-staging / e2e / promote-prod:** pull the **same digest**; prod is
  `when: manual` + protected environment + deployment approval + `ALLOW_PROD_DEPLOY`.
  `when: manual` governs *when*, the protected environment governs *who*.

---

## 5. Container image (Phase 1 target)

Multi‑stage, non‑root, digest‑pinned. The build stage runs `npm ci && npm run build`;
the serve stage is `nginx-unprivileged` (uid 101, listens `:8080`) with our hardened
server block, `/healthz`, SPA fallback, `/api` proxy (upstream from `API_UPSTREAM` at
runtime), and security headers. Base images pinned by `@sha256` resolved **from your
internal mirror** — never trust an example digest.

```dockerfile
# syntax=docker/dockerfile:1.7
ARG REGISTRY_MIRROR=registry.brb-tech.uz/dockerhub-proxy
FROM ${REGISTRY_MIRROR}/library/node:22.22.3-bookworm-slim@sha256:<PIN-ME> AS build
WORKDIR /app
ENV npm_config_fund=false npm_config_audit=false CI=true
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
RUN npm run build && test -f dist/index.html

FROM ${REGISTRY_MIRROR}/nginxinc/nginx-unprivileged:1.27-bookworm@sha256:<PIN-ME> AS serve
COPY deploy/nginx.container.conf /etc/nginx/templates/default.conf.template
COPY --from=build --chown=101:101 /app/dist /usr/share/nginx/html
ENV API_UPSTREAM="" API_READ_TIMEOUT="120s"   # empty default → insecure deploy fails closed
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -q --spider http://127.0.0.1:8080/healthz || exit 1
USER 101
STOPSIGNAL SIGQUIT
```

---

## 6. Supply‑chain gates (sequenced by ROI)

**Floor (Phase 2):** `npm ci` + lockfile‑clean check; `npm audit` (HIGH blocking);
Trivy image scan (HIGH/CRITICAL blocking, fail‑closed); one retained CycloneDX SBOM;
bases pinned by internally‑mirrored digest (reject placeholder digests at build).

**Later (Phase 4):** **cosign** sign + verify‑on‑pull (key‑based, **no** keyless/Rekor
in an air‑gap). SLSA provenance after that. These are *not* the floor — for a single
registry you control, digest‑pinning + protected immutable tags already give the
integrity property.

---

## 7. Quality gate, from zero

Repo has **zero tests / zero lint** today. Build it up, gating merge on protected `main`:

1. **Static:** ESLint flat config + `eslint-plugin-vue` (+ `v-html` ban), Prettier, `vue-tsc`.
2. **Unit (Vitest):** start with the logic that branches — `src/api.ts` response
   normalisation/error handling and `useAuth`. Per‑file floor ≥90% on those; global 0.
3. **Component (@vue/test-utils):** router guard, `PipelineResult.vue` status matrix,
   `LoginView`. Raise global floor to ~30%.
4. **E2E (Playwright):** auth + pipeline `@smoke` against the built image with `/api` mocked.
5. **Don't test what has no logic** — presentational/animation components get no unit
   tests (brittle snapshot churn); no pixel snapshots in CI initially.

> Honest: writing these suites is **weeks** of effort, not the days of scaffolding.
> A coverage gate protects nothing until the tests exist.

---

## 8. Governance & compliance (bank)

- **Protected `main`:** MR‑only, author ≠ approver, **CODEOWNERS** over
  `deploy/**`, `.gitlab-ci.yml`, `Dockerfile`, `nginx*.conf`, `SECURITY.md`.
- **Protected environments** `staging` + `production` with deployment approvals;
  **3‑way segregation of duties**: MR author ≠ MR approver ≠ deploy approver.
- **Least‑privilege runners:** the build runner holds no prod credentials; the deploy
  runner is restricted to protected refs.
- **Audit trail:** every prod deploy is a GitLab Deployment row (commit, pipeline,
  user, time) + image digest + SBOM + scan report, retained per the bank's policy
  (raise the default 1‑week artifact expiry); Audit Events → SIEM.
- **Secrets/TLS:** GitLab protected+masked variables (or Vault); TLS from the bank
  internal CA/ACME (not self‑signed); the proxy→backend hop must become TLS/mTLS.

---

## 9. Must‑fix blockers {#must-fix-blockers}

1. **(cross‑team) Client‑asserted identity = no auth** — see §1. Frontend sends a real
   Bearer token and stops sending identity; **backend** derives identity from the token
   and ignores the body. Enforced only when the backend changes.
2. **(cross‑team) Cleartext PII on proxy→backend** — see §1. `https` + `proxy_ssl_verify`
   + pinned CA; mTLS. "Trusted internal segment" is not an acceptable carve‑out for PII at a bank.
3. **Stop shipping `vite preview` as production** — build an immutable image; the host only runs it.
4. **No quality gate exists** — add lint + type‑check + tests (weeks of real work).
5. **No supply‑chain gate** — npm audit + Trivy + SBOM + digest‑pinned bases (cosign later).
6. **Governance not yet enforced in GitLab** — protected branches/environments + SoD + least‑privilege runners.
7. **Stale CSP hash = present white‑screen bug** — nginx pins `sha256-Ayug…` but the
   built inline bootstrap hashes to `sha256-bWXyvAkpiATyGEOZTMJSzDmSw9DJqJ02l/04tssKQD8=`.
   Under strict CSP the inline script is blocked and the SPA white‑screens. **Fix:**
   move the inline bootstrap to an external hashed `/bootstrap.js` and drop the
   `script-src` hash; if kept inline, add a CI step that recomputes and diffs the hash.
   (Latent today because `vite preview` sends no CSP — bites in Phase 1.)
8. **Ownership meta‑blocker:** #1 and #2 are backend deliverables with no card in this
   plan. Make `ALLOW_PROD_DEPLOY` contingent on the **backend's** signed verification.

---

## 10. Right‑sizing — what we deliberately do **not** do (yet)

- **No Kubernetes.** One SPA, one host. Rootless Podman + host‑nginx blue/green gives
  zero‑downtime + instant rollback without an orchestrator. The build‑once/promote‑digest
  contract is orchestrator‑agnostic — adopt k8s only when a second node exists.
- **cosign/SLSA are not the floor** — defer to Phase 4; digest‑pinning + protected tags
  suffice for one registry you control. Don't build a Vault‑cosign‑airgap pipeline for a
  ~400 KB bundle while the real blockers stay open.
- **No provenance theater** — no `SOURCE_DATE_EPOCH` mtime games (Vite assets are
  content‑hashed); one SBOM, not three; key‑based cosign only, no Rekor in an air‑gap.
- **Don't over‑split governance/test config up front** — land protected main + protected
  prod env + one build runner first; layer the full SoD/CR/SIEM lattice as traffic grows.

---

## 11. The biggest enterprise gap an auditor asks about first

Not a missing signature — the **single server is an unmitigated SPOF** (registry blobs,
TLS keys, deployment/audit records, the running app) with **no backup/restore runbook**.
A documented, **tested** host‑rebuild + off‑host backup (registry blobs, GitLab DB, TLS
material) with an agreed RTO/RPO **outranks cosign** in priority. On one box you do not
get a network trust boundary between build and run — say "separate service accounts +
rootless build," not "separate hosts."

---

## 12. Staged roadmap

| Phase | Goal | Key actions | Deploy |
|-------|------|-------------|--------|
| **0 — Foundation** | Infra + governance | Verify egress; provision mirrors (if air‑gapped); install Podman/Buildah + GitLab runners (`brb-build`, `brb-deploy`); protect `main` + CODEOWNERS + Secret‑Detection | OFF |
| **1 — Containerize + fix white‑screen** | Kill `vite preview` in prod | **First** externalise the inline bootstrap + drop the stale CSP hash; add multi‑stage Dockerfile + container nginx (`/healthz`, SPA fallback, `/api`, headers, empty fail‑closed `API_UPSTREAM`) + `.dockerignore`; build by SHA → registry; run container on `:8080`, repoint host nginx | OFF |
| **2 — Supply‑chain floor** | Block on vulns | lockfile‑clean, npm audit (HIGH), Trivy (HIGH/CRITICAL, fail‑closed), one SBOM, digest‑pin bases | OFF |
| **3 — Quality gate from zero** | Real CI | ESLint/Prettier/type‑check → Vitest (`api.ts`, `useAuth`) → component tests → Playwright `@smoke`; ratcheting coverage | OFF |
| **4 — Staging + promote + rollback + DR** | Real CD | Protected staging+prod envs + approvals (SoD); deploy‑staging → e2e → promote same digest; blue/green + auto‑rollback; **add cosign**; **DR runbook + tested off‑host backup** | Staging auto, prod **manual** |
| **5 — Close the two blockers (cross‑team)** | Enterprise‑ready | Agree OIDC + cert/mTLS contract; frontend sends Bearer, backend ignores body identity + TLS/mTLS on the hop; rewrite `SECURITY.md` against the real Vue/markdown‑it/DOMPurify stack; AppSec sets `ALLOW_PROD_DEPLOY=true` | Prod ON |

### Phase 0 commands

```bash
# 0.1 — verify egress (run on the runner host; re-run AS the runner user later)
for u in https://gitlab.brb-tech.uz https://registry.npmjs.org \
         https://registry-1.docker.io/v2/ https://ghcr.io/v2/ https://packages.gitlab.com; do
  printf '%-42s ' "$u"; curl -fsS -o /dev/null -m 8 -w 'HTTP %{http_code}\n' "$u" 2>/dev/null || echo "BLOCKED/timeout"
done

# 0.2 — build runtime (rootless, no daemon) [root]
sudo apt-get update && sudo apt-get install -y podman buildah && buildah version

# 0.3 — GitLab Runner [root]; get glrt- tokens from Settings → CI/CD → Runners → New project runner
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
sudo apt-get install -y gitlab-runner && gitlab-runner --version
sudo gitlab-runner register --non-interactive --url https://gitlab.brb-tech.uz \
  --token "<glrt-BUILD>"  --executor shell --description "brb-build"  \
  --tag-list "brb-build"  --run-untagged=false --locked=true
sudo gitlab-runner register --non-interactive --url https://gitlab.brb-tech.uz \
  --token "<glrt-DEPLOY>" --executor shell --description "brb-deploy" \
  --tag-list "brb-deploy" --run-untagged=false --locked=true --access-level=ref_protected
sudo systemctl enable --now gitlab-runner && gitlab-runner list

# 0.4 — CODEOWNERS lives at .gitlab/CODEOWNERS (template committed; set real groups)

# 0.5 — governance (GitLab UI): protect main (MR-only, code-owner approval), MR rules
#        (author/committer can't approve), enable Secret Detection + SAST, leave
#        ALLOW_PROD_DEPLOY UNSET. API example (maintainer token):
# curl -fsS -X POST -H "PRIVATE-TOKEN: $GLAB_TOKEN" \
#   "https://gitlab.brb-tech.uz/api/v4/projects/<ID>/protected_branches?name=main&push_access_level=0&merge_access_level=40&code_owner_approval_required=true"
```

> Air‑gap note: if 0.1 shows `npmjs`/`docker.io` blocked, set `npm_config_registry`
> (Protected CI var) to your Nexus npm‑proxy, mirror the base images into your
> registry, and stand up a Trivy DB mirror — **before** Phase 1's first build.

---

## 13. Host gotchas (runbook)

Two things cost real debugging time bringing CD up on this host. Both are **host
state, not repo state** — a rebuilt or replacement server will hit them again.

### 13.1 `~/.bash_logout` breaks *every* shell-executor job

**Symptom.** Every job on a `shell` runner dies instantly (~15 ms), before any
script runs:

```
ERROR: Job failed: prepare environment: exit status 1.
Check https://docs.gitlab.com/runner/shells/#shell-profile-loading
```

**Cause.** GitLab Runner starts jobs with `bash -l`. Ubuntu's stock
`~/.bash_logout` runs `clear_console` when `SHLVL = 1` — exactly how the runner
spawns bash. With no TTY attached `clear_console` fails, so the **login shell exits
non-zero**, and the runner reports it as a profile-loading failure.

It is invisible to casual testing: an interactive session already has `SHLVL ≥ 2`,
so that guarded branch never executes and `bash -l -c true` happily returns 0.
The shell profile itself is fine — the error message is misleading.

**Fix** (as the runner's user — here `ymamajonov`):

```bash
cp ~/.bash_logout ~/.bash_logout.bak
printf 'true\n' > ~/.bash_logout        # drop the clear_console block

# verify — must print 0:
env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin SHLVL=0 \
  setsid bash -l -c 'true' </dev/null >/dev/null 2>&1; echo $?
```

### 13.2 The deploy runner must be USER-mode, not `sudo`

`deploy:production` asserts `id -un = ymamajonov` in its `before_script`, because
the cutover drives **rootless podman** and the `--user` systemd units owned by that
account. A runner registered with `sudo` executes jobs as `gitlab-runner` and trips
that assertion immediately. Register it **without sudo**, into the user's own
config, and run it as a `--user` service with linger on:

```bash
gitlab-runner register --non-interactive \
  --config "$HOME/.gitlab-runner/config.toml" \
  --url https://gitlab.brb-tech.uz/ --token "<glrt-DEPLOY>" \
  --executor shell --description "brb-deploy (user=ymamajonov)"
# tag / protected / run-untagged come from the runner's settings in the GitLab UI:
#   tag = llm-brb-tech-deploy-user, "Run untagged jobs" OFF, "Protected" ON

loginctl enable-linger "$USER"          # survive logout / reboot
systemctl --user enable --now gitlab-runner
```

> ⚠️ Section 0.3 registers **both** runners with `sudo`. That is right for the
> **build** runner only — the deploy runner must follow 13.2.

### 13.3 Protected environments are Premium

`deploy:production` declares `environment: name: production`, but **Protected
Environments is a GitLab Premium feature** and is unavailable on this instance, so
the "who may deploy" approval gate cannot be enforced there. The remaining gates
still hold: `when: manual`, default-branch-only, the **protected** `ALLOW_PROD_DEPLOY`
variable, and a **protected** runner. Access control therefore rests on `main` being
a protected branch (Maintainers-only merge, no direct push).
