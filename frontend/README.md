# Venera — Frontend

A standalone Vue 3 + TypeScript single-page app for **Venera**.
It is a thin client over the Spring Boot RAG backend: it sends a user question to
one endpoint and renders the pipeline result (guard → intent → orchestrator →
access, and retrieval when available).

The frontend talks **only** to the Spring Boot backend — never directly to the
BGE-M3, Qdrant, or reranker services (per the API contract).

---

## Tech stack

- **Vue 3** + **TypeScript**
- **Vite 8** (dev server + build)
- **vue-router**, **vue-i18n** (uz / uz-Cyrl / ru / en)
- **markdown-it** + **DOMPurify** (answer rendering)
- No CSS framework — styling is scoped SFC CSS + a token-driven `index.css`

---

## Quick start

```bash
# from this folder: Venera/frontend
npm install

# copy the env template and point it at your backend
cp .env.example .env       # then edit VITE_API_BASE if needed

npm run dev                # dev server (Vite default port 5173)
```

Open the URL Vite prints (e.g. `http://localhost:5173`).

### Scripts

| Command | What it does |
| --- | --- |
| `npm run dev` | Start the Vite dev server with HMR |
| `npm run build` | Type-check (`tsc -b`) + produce a production bundle in `dist/` |
| `npm run preview` | Serve the built `dist/` locally |

---

## Configuration

All config lives in `.env` (see `.env.example`). One variable matters:

```env
VITE_API_BASE=http://10.10.50.9:8080
```

There are two ways to run, depending on whether the backend allows CORS from the
frontend's origin:

1. **Direct mode (default).** `VITE_API_BASE` is an absolute URL → the browser
   calls the backend directly. The backend must allow CORS for the frontend
   origin. (Verified working against `http://10.10.50.9:8080`.)

2. **Proxy mode.** Set `VITE_API_BASE=""` (empty) → API calls become relative and
   Vite's dev server forwards `/api` to `VITE_API_TARGET` (falls back to the same
   address). Useful when CORS isn't configured yet. A production build in this
   mode needs a reverse proxy in front of the static bundle.

`.env` is gitignored; commit changes to `.env.example` instead.

---

## API contract

The app calls a single endpoint:

```
POST {VITE_API_BASE}/api/v1/chat/pipeline
Content-Type: application/json
```

**Request** (`src/types.ts → PipelineRequest`):

```json
{
  "actorType": "EMPLOYEE",
  "actorId": "E12345",
  "email": "user@venera.uz",
  "roles": ["EMPLOYEE"],
  "department": "AI_DEPARTMENT",
  "question": "Menga ta'til olish tartibini tushuntiring"
}
```

**Response** (`PipelineResponse`): `{ finalStatus, guard, intent, orchestrator, access, retrieval, answer? }`.

The UI branches on `finalStatus`:

| `finalStatus` | UI |
| --- | --- |
| `READY_FOR_RETRIEVAL_OR_ANSWER` | Green "Ready" badge + the pipeline trace; renders `answer` / `retrieval` chunks when present |
| `STOP_UNSAFE` | Red badge with the guard's refusal reason |
| `STOP_ACCESS_DENIED` | Amber badge with the access reason |

All API types mirror the backend contract exactly — change `src/types.ts` only
when the contract changes.

---

## Features

- **Light / dark theme** — toggle in the header (sun/moon), persisted to
  `localStorage`, defaults to the OS preference, set before first paint to avoid
  a flash. Driven entirely by CSS variables in `index.css`.
- **Frosted-glass surfaces** — the answer box, suggestion chips, identity pill,
  dropdown, and user bubbles use `backdrop-filter`; dense data panels stay solid.
- **Ambient glow** — a static warm backdrop pooled behind the answer box.
- **Demo identity** — the actor fields (`actorType`, `actorId`, `email`, `roles`,
  `department`) are edited via the header pill and cached in `localStorage`. In
  production these should come from an auth token, not manual input.
- **Pipeline trace** — collapsible Guard / Intent / Orchestrator / Access /
  Retrieval stages with decision, reason, model, and timing. Expanded by default
  for `RAG_ADMIN`, collapsed for `EMPLOYEE` / `CUSTOMER`.

---

## Project structure

```
src/
├── main.tsx            # React entry
├── App.tsx             # Shell: identity + theme state, send() → postPipeline()
├── api.ts              # postPipeline() — the single backend call
├── types.ts            # Request/response types (mirror the contract)
├── theme.ts            # Theme read/apply/persist
├── icons.tsx           # Inline SVG icons
├── index.css           # Theme tokens (light/dark), glass utilities, keyframes
└── components/
    ├── AmbientBackground.tsx   # Static glow
    ├── Header.tsx              # Title + theme toggle + identity
    ├── IdentityBar.tsx         # Demo identity pill + editor
    ├── Welcome.tsx             # Greeting + role-based suggestion chips
    ├── InputDock.tsx           # The answer box
    ├── Conversation.tsx        # Question/answer thread (in-memory)
    ├── PipelineResult.tsx      # Result card + status badge
    └── TraceStages.tsx         # Collapsible per-stage trace
```

---

## Notes & current limitations

- **Answer text is pending backend wiring.** For `READY_FOR_RETRIEVAL_OR_ANSWER`,
  the backend currently returns no `answer`/`retrieval`, so the UI shows a
  placeholder. The frontend already renders `answer` (markdown) and `retrieval`
  chunks as soon as the backend provides them.
- **No authentication yet.** Identity is entered manually for the demo; wire it to
  the real auth token/session before production.
- **Conversation history is in-memory** — it resets on reload (no persistence
  endpoint in the current contract).
