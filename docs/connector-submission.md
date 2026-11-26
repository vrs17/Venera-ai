# Barno connector - directory submission package (Claude and ChatGPT)

Prepared 2026-11-26. Everything to copy into the Anthropic (Claude) and OpenAI (ChatGPT) submission forms,
plus the steps the owner does himself. Design and security: `docs/barno-connector.md`.

## 1. Ready on our side

| Item | Value |
|---|---|
| Name | Barno AI |
| MCP server URL | `https://llm.brb-tech.uz/mcp` |
| Transport | Streamable HTTP, stateless, JSON responses. MCP 2026-07-28 and 2025-11-25 / 2025-06-18 / 2025-03-26 |
| Authentication | OAuth 2.1 (Barno is its own authorization server): PKCE S256, Client ID Metadata Documents and Dynamic Client Registration, RFC 9207 `iss`, tokens bound to the resource |
| Documentation | https://llm.brb-tech.uz/connector |
| Privacy policy | https://llm.brb-tech.uz/privacy (section 9 covers the connector) |
| Terms of use | https://llm.brb-tech.uz/connector/terms |
| Support | y.mamajonov@brb-tech.uz |
| Company | BRB-Tech |
| Logo | `docs/connector-assets/barno-256.png` (256x256, 1.7 KB - ChatGPT wants PNG <= 10 KB), `barno-512.png` (512x512) |
| Category | Productivity |
| Who can sign in | BRB-Tech employees with a BRB-Tech ID account only |

## 2. Listing text

**Short description** (one line):

> Read your Barno AI meeting notes - summaries, transcripts and action items - right in the chat.

**Long description:**

> Barno AI is BRB-Tech's work assistant. The Barno connector lets BRB-Tech employees read their own
> meeting recordings from Barno (Plaud and the Barno recorder) inside Claude or ChatGPT: find a meeting,
> get its summary, decisions and action items, read the transcript with speaker names, or pull the formal
> minutes. Access is read-only and limited to the signed-in person's own meetings. Each person signs in
> with their BRB-Tech ID and approves the connection on Barno's permission screen, and can disconnect at
> any time in Barno under "Connected apps". Barno logs who called which tool and when, never the content.

**Example prompts:**

1. "What meetings did I have this week? Summarise the most important one."
2. "List my open action items from all meetings, grouped by owner."
3. "Find the meeting about the hackathon and tell me the final rules that were agreed."
4. "Show me what was said about the budget in my last meeting, with timestamps."
5. "Get the minutes of yesterday's meeting and draft a follow-up email from them."

**Tools** (all read-only: `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`,
`openWorldHint: false`; every tool has a `title`):

| Tool | Title | What it does |
|---|---|---|
| `search_meetings` | Search meetings | The person's own meetings, newest first, with an optional text query |
| `get_meeting` | Get meeting | One meeting: title, date, duration, speakers, status |
| `get_summary` | Get meeting summary | Summary as Markdown: overview, topics, decisions, action items |
| `get_transcript` | Get meeting transcript | Transcript lines `[hh:mm:ss] Speaker: text`, paged |
| `list_action_items` | List action items | Action items for one meeting or across all meetings |
| `get_minutes` | Get meeting minutes | Formal minutes as Markdown, if prepared in Barno |
| `search` | Search | ChatGPT deep-research search over the person's meetings |
| `fetch` | Fetch meeting | ChatGPT deep-research fetch: one meeting as a document |

**Data handling (for the privacy questions):** data returned = the person's own meeting titles, dates,
summaries, transcripts, action items and minutes. No data is written or deleted. Call log = actor, app,
tool, time, status, response size (no content), kept 90 days. Tokens: access 1 hour, refresh 30 days,
rotated; revoked on disconnect, on account block and on admin sign-out. Rate limit 60 calls per minute
per connection.

## 3. Reviewer test account (owner does this)

Reviewers cannot receive SMS or authenticator codes, so the account must sign in with **username and
password only**.

1. In BRB-Tech ID (Keycloak `brb-realm`, the admin console you already use - add only) create a user,
   for example `barno.review`, with a password. Leave "Required user actions" empty, and do not set up an
   authenticator (OTP) for it.
2. Sign in once with it at https://llm.brb-tech.uz to check it works.
3. Give it 2-3 meetings: while signed in as the test user, record or upload the two practice meetings
   from section 4 (in English, so the reviewers can follow). Wait until each shows a summary.
4. Send me the username only. You type the password into the submission forms yourself.

## 4. Two practice meetings for the test account (read aloud, 2-3 minutes each)

**A. "Weekly product sync"** (two people, A and B)

- A: Let's start the weekly product sync. First item: the mobile app release.
- B: The release candidate is ready. QA found two small bugs in the login screen; fixes will be done by Thursday.
- A: Good. Then we release next Monday. B, you own the release notes, due Friday.
- B: Agreed. Second item: customer feedback. Most requests are about exporting meeting notes to PDF.
- A: Let's add PDF export to next month's plan. I'll write the requirements by Wednesday.
- B: Last item: the budget for the design contractor is approved, 2,000 dollars for this quarter.
- A: Great. Decisions: release on Monday, PDF export goes to next month's plan. Thanks, everyone.

**B. "Hackathon planning"**

- A: This is the hackathon planning call. The hackathon runs on the 12th and 13th of December.
- B: We have eight teams registered. Judging criteria: impact 40 percent, technical quality 40, demo 20.
- A: The checkpoint is on day one at 6 pm. Teams must show a working prototype.
- B: I'll book the hall and send the schedule to all teams by Monday.
- A: I'll invite three judges from partner companies by Friday.
- B: Final rule: demos are five minutes each, plus two minutes of questions.
- A: Agreed. Action items: B books the hall and sends the schedule, A invites the judges.

## 5. Test cases (OpenAI asks for 5 positive and 3 negative)

Positive (signed in as the test account, connector approved):

1. "List my meetings." - returns the 2-3 practice meetings with dates and durations.
2. "Summarise the weekly product sync." - summary with the release-on-Monday decision.
3. "What are my open action items?" - release notes (B, Friday), PDF requirements (A, Wednesday), hall, judges.
4. "What were the hackathon judging criteria?" - impact 40%, technical quality 40%, demo 20%.
5. "Show the transcript of the hackathon call." - transcript lines with timestamps and speakers.

Negative:

1. "Delete my last meeting." - the assistant explains it cannot; the connector has no write tools.
2. "Show me other employees' meetings." - only the test account's own meetings are returned.
3. Disconnect the app in Barno ("Connected apps" - "Disconnect"), then ask "List my meetings." - the
   assistant gets an authorization error and asks to reconnect.

## 6. Steps - Claude directory (Anthropic)

1. Open the Claude connector directory submission page (linked from
   https://claude.com/docs/connectors/building/submission) while signed in to the BRB-Tech Anthropic
   organization account (Team/Enterprise: the organization owner submits).
2. Fill the form from sections 1 and 2: name, URL, descriptions, logo, example prompts, documentation,
   privacy and terms links, support email.
3. Confirm the policy statements (read each one; they are about data use, security and accuracy of the
   listing).
4. Add the reviewer account from section 3 (username, password typed by you).
5. Submit. The listing usually starts as "Community" and can later become "Verified" after review.

## 7. Steps - ChatGPT app directory (OpenAI)

1. Sign in to the OpenAI platform with the BRB-Tech organization account. If OpenAI asks to verify the
   organization, finish that first.
2. Create the app and enter the MCP server URL `https://llm.brb-tech.uz/mcp` (OAuth).
3. **Domain verification:** OpenAI shows a code for `llm.brb-tech.uz`. Put it into
   `~/Barno_AI/venera/apps/api/.env` as one line `OPENAI_APPS_CHALLENGE=<code>` (no restart needed).
   Barno then serves it at https://llm.brb-tech.uz/.well-known/openai-apps-challenge. Tell me and I check
   it from outside, then press "Verify".
4. Fill the listing from sections 1 and 2 (logo: `barno-256.png`).
5. Add the reviewer account (section 3) and the test cases (section 5).
6. Record a short screen video: add the connector, sign in, approve on Barno's permission screen, ask
   prompts 1-3 from section 5. No real company meetings in the video - use the test account.
7. Submit.

## 8. Open items before submitting

- Meeting links in tool results open `/meeting/<id>`, a phone-app path; on the website they land on the
  home page. Reviewers may click them. Fix: add a meeting page to the website (planned).
- The privacy policy lists `ai@brb-tech.uz` as its contact, the connector pages list
  `y.mamajonov@brb-tech.uz`. Use one address everywhere or make sure both are monitored.
