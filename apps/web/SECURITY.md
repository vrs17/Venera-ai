# Security notes

Status of the frontend's security posture and the items that **must** be resolved
before this is exposed to untrusted users. Reviewed 2026-06-16.

## 🔴 Release blockers — do NOT deploy to production until resolved

### 1. Identity is client-asserted — no authentication

The frontend sends the actor's identity in the request body and lets the user edit
all of it via the header identity pill:

```jsonc
// src/types.ts → PipelineRequest, set in src/components/IdentityBar.tsx
{ "actorType": "RAG_ADMIN", "actorId": "...", "email": "...",
  "roles": ["..."], "department": "..." , "question": "..." }
```

Anyone can open the pill and set `actorType: RAG_ADMIN` with arbitrary `roles` and
`department`. If the backend makes its access decisions (`STOP_ACCESS_DENIED`,
`requiredRole`, `resourceScope`) from these **client-supplied** values, the access
control is fully bypassable (privilege escalation / IDOR).

This is intentional for the demo (see README "No authentication yet"), but is a
**hard blocker** for production.

**Required fix:**
- Authenticate the user (SSO / OIDC / session) and send a **verified bearer token**
  (`Authorization: Bearer …`) from [`src/api.ts`](src/api.ts).
- The backend must derive `actorType` / `actorId` / `roles` / `department` from the
  token and **ignore** any identity fields in the request body.
- Remove or gate the editable identity pill ([`src/components/IdentityBar.tsx`](src/components/IdentityBar.tsx))
  so identity can't be spoofed from the client.

### 2. Backend transport is plaintext HTTP

Default backend is `http://10.10.50.9:8080`. PII (email, employee ID,
department, roles) and user questions cross the network unencrypted.

**Required fix:** HTTPS end-to-end. The production proxy ([`deploy/nginx.conf`](deploy/nginx.conf))
terminates TLS at the edge and sets HSTS + `upgrade-insecure-requests`, but the
**proxy → backend hop is still HTTP** — secure that hop (TLS/mTLS) if it crosses
any untrusted network segment.

## 🟡 Recommended hardening (not blockers)

- **Self-host the Figtree font.** Currently loaded from `fonts.googleapis.com` /
  `fonts.gstatic.com` ([`index.html`](index.html)) — leaks user IPs to Google and
  widens the CSP. Self-host, then tighten CSP to `style-src 'self'` / `font-src 'self'`.
- **Keep the CSP in sync.** [`deploy/nginx.conf`](deploy/nginx.conf) pins the inline
  bootstrap script by sha256 hash. If you edit that script in `index.html`,
  recompute the hash (see [`deploy/README.md`](deploy/README.md)) or the app won't boot.

## ✅ Verified good (no action needed)

- `npm audit`: **0 vulnerabilities** (full tree and production-only).
- Production build emits **no source maps**; no secrets in the bundle or repo; `.env` is gitignored.
- No `dangerouslySetInnerHTML`, `eval`, `innerHTML`, or `document.write` anywhere.
- All user and backend data renders through React's auto-escaping JSX.
- `react-markdown` runs **without** `rehype-raw` → HTML in backend answers is
  escaped and `javascript:` URLs are stripped. The CSP `img-src 'self' data:` also
  blocks image-beacon exfiltration from a malicious/prompt-injected answer.
- Proxy-mode build keeps the internal backend IP out of the shipped JS.
