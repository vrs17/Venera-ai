# Origin of the web app (`apps/web`)

> **TARIXIY HUJJAT — ataylab o'zgartirilmagan.**
>
> Quyidagi manzillar, repo nomlari va digest'lar **haqiqiy** va o'sha paytdagi
> holatni qayd etadi. Ularni "Venera" ga almashtirsak, hujjat yolg'onga aylanadi
> va keyin kimdir mavjud bo'lmagan manzilni qidiradi. Shuning uchun bu yerda
> eski nomlar saqlanib qolgan — boshqa hamma joyda ular Venera'ga o'zgartirilgan.
>
> Bugungi holat:
> - Papka `frontend/` emas, **`apps/web/`**.
> - Loyiha **Venera** deb nomlandi va yuqoridagi GitLab repo'sidan **uzildi** —
>   endi rivojlantirish shu monorepo ichida boradi, upstream'dan tortilmaydi.

This directory is a copy of the frontend that was **live** at
<https://llm.brb-tech.uz> when it was copied.

## Source

| | |
|---|---|
| Upstream repo | `registry.brb-tech.uz/y.mamajonov/brbtechllm_frontend` (GitLab) |
| Local checkout it was taken from | `/home/ymamajonov/brbtechllm_frontend/brbtechllm_frontend` |
| Commit | `676a3b4deb6b3ec083a3efb7b979691ee19dfc46` (`main`, 2026-07-29) |
| Equivalent commit | `ca5262954907f066dd6a7b40abe924483e9c457e` (2026-07-22) — identical build output |
| Live image digest | `sha256:c3ac3799f5e4ed72036ae56c8353b9b2997b13da42671cb9d4ebb25cebdfe1f9` |
| Copied on | 2026-09-04 |

The two commits differ only in dev-only settings (the Vite dev-proxy target and
docs), which is why both tags point at the same image digest.

## How the copy was verified

`npm ci && npm run build` was run on the exported commit and every emitted file
was compared byte-for-byte against the files inside the running container
(`/usr/share/nginx/html`): **26/26 identical**, including the content-hashed
bundle names `index-pj7kHMK8.js` and `index-BKSRENEB.css`. So this source is
provably the source of the running site — not an approximation.

## What was left out

- `node_modules/`, `dist/` — build artifacts, regenerate with `npm ci && npm run build`.
- `.claude/` — editor-local config belonging to the upstream repo.
- `.env` — gitignored upstream; recreated here from the working LAN config.

## Production topology it was serving

```
llm.brb-tech.uz:443 (edge nginx, *.brb-tech.uz cert)
   -> 10.10.50.8:5173            systemd --user unit container-brb-frontend.service
   -> container :8080            nginx 1.27.5, root /usr/share/nginx/html
   -> /api/ proxied to 10.10.50.9:8080   (Spring Boot)
```

`deploy/` and `.gitlab-ci.yml` came along as reference. They still point at the
BRB GitLab project, registry and hosts — adapt them before using them for
Venera, and note that a nested `.gitlab-ci.yml` is not picked up by GitLab
(only a repo-root one is).

## Getting started

```bash
cd frontend
npm ci
npm run dev      # Vite dev server, /api proxied to VITE_API_TARGET
npm run build    # type-check (vue-tsc) + production bundle into dist/
```

Requires Node 22 (built and verified with v22.22.3 / npm 10.9.8).
