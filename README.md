# Agentic AI Grievance Redressal System

HackFusion 4.0 prototype. A district grievance portal where AI agents handle
intake, evidence retrieval, policy gating, routing and SLA monitoring, while a
deterministic guard layer enforces the safety rules that AI output is never
allowed to override.

> **Data notice.** The supplied CSVs are synthetic demonstration data. They are
> not official government records. Every email address and webhook ID in them is
> a non-operational placeholder, and the system refuses to dispatch anything to
> an address that is not a reserved placeholder domain.

---

## Status

| Milestone | Scope | State |
|---|---|---|
| **M1** | Backend, CSV loading, policy guards, hard-rule tests | **done** |
| **M2** | Traced LangGraph pipeline + scenarios 1 and 2 | **done** |
| **M3** | Officer console (queue, explainability, approve/override) | **done** |
| **M4** | Duplicate grouping + SLA alerts + scenario 3 | **done** |
| **M5** | Citizen chat, voice, Marathi/Hindi, tracking + dispute | **done** |
| **M6** | Bonus: taluka hotspot analytics | **done** |

---

## The core design rule

**Nothing about a category, SLA, policy flag, department, taluka or contact is
hardcoded anywhere.** All of it is read from the CSVs in `DATA_DIR` at runtime,
and the configuration tables are replaced wholesale on reload. Replacing a CSV
changes routing, SLAs and policy with no code edit — proven by
`tests/test_csv_swap.py`, which loads a fixture master that disagrees with the
supplied one on department, SLA, priority and flags, and asserts the behaviour
changes accordingly.

The three policy flags (`sensitive`, `identity_hiding`, `auto_resolution_allowed`)
are evaluated **independently**. In the supplied file they happen to coincide on
the same five categories; the fixture includes a category that is
identity-hiding without being sensitive, so that coincidence can never be
mistaken for a rule.

## The eight hard rules

Enforced in `backend/app/policy/guards.py` as deterministic code called by the
service layer — not as prompt instructions. One test group per rule in
`backend/tests/test_hard_rules.py`.

| # | Rule | Enforced by |
|---|---|---|
| 1 | A Sensitive case is never auto-closed | `authorize_status_change` |
| 2 | The AI never auto-rejects or rules on liability | `authorize_status_change` status allow-list |
| 3 | Identity-Hiding categories are masked in department views, webhooks and notifications | `mask_identity` |
| 4 | Every AI action is audited with actor, model, confidence, timestamp, reasoning | `build_audit_entry` |
| 5 | Every decision stores confidence, retrieved cases and the rule applied | `build_decision_record` |
| 6 | AI summaries, scores and assessments are labelled, never verified facts | `label_ai_output` |
| 7 | Priority = severity + urgency + affected population, never submission count | `PriorityInputs` / `compute_priority` |
| 8 | Nothing is ever sent to a real address | `assert_mock_destination` |

Two of these deserve a note:

- **Rule 2** is an allow-list, not a list of rejection words. An automated actor
  may set only the configured statuses; anything else — including a status a
  replacement CSV invents — is refused. That holds without guessing at
  rejection vocabulary.
- **Rule 7** is enforced by the type signature. `PriorityInputs` has exactly
  three fields and no parameter for duplicate or submission count, so volume
  cannot drive priority even by mistake.

A refused action is itself written to the audit log (`REFUSED_*`), so the trail
shows that the system was asked to auto-close a sensitive case and declined.

---

## Setup

```bash
cd backend
python -m pip install -r requirements.txt
```

```bash
cp backend/.env.example backend/.env
```

Postgres with pgvector, from the repo root:

```bash
docker compose up -d
```

Load the CSVs:

```bash
cd backend && python scripts/load_data.py
```

Embed the history for semantic retrieval:

```bash
cd backend && python scripts/embed_history.py
```

Run the API:

```bash
cd backend && python -m uvicorn app.main:app --reload --port 8000
```

Run the tests:

```bash
cd backend && python -m pytest
```

The test suite runs on in-memory SQLite and needs no database server, no
network and no API key. Only pgvector similarity search requires Postgres.

### Environment variables

Names only; no values are committed.

| Variable | Purpose |
|---|---|
| `DATA_DIR` | Directory holding the three CSVs. Swap a file here to change behaviour. |
| `DATABASE_URL` | Any Postgres URL — local Docker, Supabase, or AWS RDS. |
| `CONFIDENCE_THRESHOLD` | Minimum confidence for an automated resolution. |
| `CLOSING_STATUSES` | Which statuses count as closing a case. |
| `AI_ALLOWED_STATUSES` | The only statuses an automated actor may set. |
| `OPENAI_API_KEY` | Agents, transcription and embeddings. |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | Retrieval embedding config. |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | Tracing. Absent = tracing disabled, nothing breaks. |
| `N8N_WEBHOOK_BASE` | Optional. Unset = recorded mock dispatch. |

---

## API (M1)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Service and loaded-data status |
| POST | `/api/admin/reload-reference-data` | Re-read the CSVs and replace config tables |
| GET | `/api/categories` | Category master with policy flags |
| GET | `/api/departments` | Department directory with parsed talukas |
| GET | `/api/grievances/history` | Keyword search over the 800 historical cases |
| POST | `/api/grievances` | Create a grievance, routed from the master |
| GET | `/api/grievances/{reference_no}` | Fetch a case; `?audience=DEPARTMENT` applies masking |
| PATCH | `/api/grievances/{reference_no}/status` | Guarded status update; 409 names the violated rule |
| POST | `/api/grievances/{reference_no}/dispute` | A disputed resolution reopens the case |
| GET | `/api/grievances/{reference_no}/policy` | The live policy governing the case |
| GET | `/api/compliance/rules` | Run every hard-rule probe against the live policy layer |
| GET | `/api/grievances/{reference_no}/pipeline` | Agent hand-offs, rebuilt from recorded data |
| GET | `/api/analytics/hotspots` | Per-taluka pressure and SLA failure, privacy-suppressed |
| GET | `/api/intake/languages` | Languages offered and whether voice is available |
| POST | `/api/intake/message` | Add a citizen turn; returns the draft, files nothing |
| POST | `/api/intake/{session_key}/confirm` | Citizen confirms; the ticket is created |
| POST | `/api/intake/transcribe` | Speech to text (Marathi, Hindi, English) |
| GET | `/api/track/{reference_no}` | Track a case as the complainant sees it |
| POST | `/api/track/{reference_no}/feedback` | Confirm or dispute; a dispute reopens |
| GET | `/api/officer/queue` | Officer work queue, identity-masked, priority ordered |
| GET | `/api/officer/grievances/{reference_no}` | One case as the officer sees it |
| POST | `/api/officer/grievances/{reference_no}/approve` | Officer agrees with the AI recommendation |
| POST | `/api/officer/grievances/{reference_no}/override` | Officer disagrees; every changed field is audited |
| POST | `/api/jobs/sla-scan?now=` | Scheduled SLA scan; raises escalation alerts |
| GET | `/api/sla/alerts` | Raised alerts with their evidence base |
| GET | `/api/sla/forecast/{reference_no}` | Full SLA assessment for one case |
| POST | `/api/incidents/group` | Run duplicate detection |
| GET | `/api/incidents` | Incident groups with every member listed |
| POST | `/api/incidents/{id}/confirm` | Officer confirms a suggested grouping |
| POST | `/api/pipeline/run` | Run the full agent pipeline on one complaint |
| GET | `/api/grievances/{reference_no}/explain` | Explainability panel: rule, confidence, retrieved cases |
| GET | `/api/audit-logs` | AI and human actions, including refusals |

All six milestones are complete.

### SLA prediction, and why it is deliberately cautious

The supplied history makes a naive predictor worthless: 65% of its closed
cases already exceeded their configured SLA, so "historical duration >
sla_days" would flag nearly every ticket. Instead:

- The p80 historical duration for the case's own category **and** department is
  compared against the SLA from the master, and the **basis** of that estimate
  is reported (`category+department`, `category`, `department`, or none) so an
  officer can tell a specific estimate from a district-wide one.
- Below `SLA_MIN_SAMPLES` (default 8) comparable closed cases, **no estimate is
  offered at all** — the risk is reported as `INSUFFICIENT_HISTORY` rather than
  invented from three data points.
- The escalation alert fires from the **deadline**, not from the prediction, so
  an alert still arrives before the due time when history is thin. The
  prediction ranks the queue; the deadline triggers the alert.
- Recurrence is reported separately: a locality that keeps producing the same
  category of complaint is a different problem from one slow ticket.

The scan takes an injectable `now`, so a pre-deadline escalation can be
demonstrated and tested without waiting for a real deadline to pass.

### Duplicates are grouped, never merged

A group requires the same category, the same place and the same time window
*before* semantic similarity is considered, and the result is a suggestion
until an officer confirms it. Every member keeps its own reference number,
status, deadline and notifications; the grouping is additive metadata with no
authority over any case. The officer view lists all members rather than
collapsing them into a count, and each link is individually audited.

One detail worth knowing: the similarity threshold **defaults per embedding
space**. Cosine values from the offline lexical embedding and from OpenAI
embeddings are not comparable, so a single fixed threshold would either group
nothing offline or group everything online.

### Seeing rule 1 refuse an auto-close

```bash
curl -s -X POST localhost:8000/api/grievances -H "Content-Type: application/json" -d '{"complaint_text":"Confidential concern.","category_id":"C018","taluka":"Kandhar","citizen_name":"Demo Citizen"}'
```

```bash
curl -s -X PATCH localhost:8000/api/grievances/REFERENCE_HERE/status -H "Content-Type: application/json" -d '{"status":"Closed","actor":"AI_SYSTEM","model":"demo","confidence":0.99,"reasoning":"agent requested closure"}'
```

Returns HTTP 409 with `"rule": "RULE_1_SENSITIVE_NEVER_AUTO_CLOSED"`. The same
request with `"actor": "OFFICER"` and an `actor_id` succeeds, because a human
officer retains the authority the AI does not have.

---

## Frontend

```bash
cd frontend && npm install
```

```bash
cd frontend && npm run dev
```

| Route | Purpose |
|---|---|
| `/citizen` | Chat intake: write or speak, in Marathi, Hindi or English |
| `/track` | Track by reference; confirm or dispute a resolution |
| `/officer` | Officer queue and incident groups |
| `/officer/{reference_no}` | One case: explainability, alerts, approve/override |
| `/officer/hotspots` | Taluka analytics: where cases concentrate and deadlines slip |
| `/compliance` | The safety contract, proved live against the running code |

It reads `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`).

> Do not run `npm run build` while `npm run dev` is running: both write to
> `.next` and the dev server will start returning 500s. Stop dev, or build in
> a separate checkout.

### Languages in the interface

The whole interface switches between Marathi, Hindi and English, not just the
citizen desk: navigation, headings, filters, status chips, priority and risk
labels. The choice persists in `localStorage` and sets
`document.documentElement.lang`, which drives the Devanagari line-height rules
and tells a screen reader which language it is reading. Each option is written
in its own script (मराठी / हिंदी / English) rather than translated into the
current one.

Record data stays in its original language on purpose. Complaint text, taluka
names, department IDs and the policy reasons written by the backend are
records of a decision, not interface copy; translating a stored decision would
misrepresent it. Rule *labels* are translated, because that is what an officer
scans.

Typography carries this: Manrope for display and body, **Noto Sans Devanagari**
for Indic text, IBM Plex Mono for reference numbers. The Devanagari face is not
decoration — without it, Marathi and Hindi fall back to whatever the device
happens to have.

### Design

Concept: **a district collectorate night desk** — dark slate ledger paper,
hairline rules instead of cards, register-column reference numbers, and status
marks stamped in oxidised copper and signal-lamp amber.

| Role | Hex | Notes |
|---|---|---|
| Page / card / sunken | `#F5F4F0` · `#FFFFFF` · `#E9E7E0` | Warm paper, never flat grey |
| Rules / ink / ink-2 / ink-3 | `#0A0A0A` · `#333330` · `#5C5C57` | 2px black rules are the structure |
| Green — the service, permitted | `#19632F` | White text on it: 7.3:1 |
| Dark yellow — time pressure only | `#A8820C` | **Black** text on it: 5.5:1 (white is only 3.6:1) |
| Red — a policy rule applies | `#B51226` | White text on it: 6.8:1 |

Green, yellow and red is the worst possible trio for colour-vision
deficiency, so these three were chosen by measurement rather than by eye:
**13.0 ΔE under deuteranopia and 22.0 for normal vision**, both clear of the
floor. Every status chip also carries a word, so colour is never the only
encoding. Dark yellow never appears as small coloured text — it appears as a
black-on-yellow chip, which is both the accessible pairing and the universal
caution signal.

Colour carries meaning and nothing else: **yellow only ever means time
pressure, red only ever means a policy rule applies**. An overdue pothole is
yellow; a sensitive case is red. Type is Manrope for display and body, Noto
Sans Devanagari for Indic text, and IBM Plex Mono for reference numbers and
labels. Radius is **zero throughout** — the design is minimal and brutalist:
2px black rules instead of borders-plus-shadows, and a hard offset block on
hover rather than a blur.

Motion has one personality (`cubic-bezier(0.16, 1, 0.3, 1)`) and three
signature moments: queue rows arriving staggered in reading order, the verdict
stamp pressing onto the case, and the confidence meter drawing to its value.
Everything animates `transform`, `opacity` and `clip-path` only, and
`prefers-reduced-motion` is honoured. No animation library is used.

### Two UI decisions worth knowing

- **A case is headlined by its category and subcategory, not by the AI
  summary.** Anything set at headline size reads as verified fact; the AI
  summary sits below it in a labelled block. Rule 6 is as much a typographic
  constraint as a code one.
- **Masked identity is shown as a withheld field, not an absence.** The
  officer sees "identity withheld by policy" rather than a blank, so it is
  clear a rule is acting rather than data being missing.

### Taluka hotspots and the map

`/officer/hotspots` ranks the 16 talukas by case volume and by the share of
closed cases that missed their SLA. In the supplied data the spread is real
and usable: Loha closes 83% of cases late against a district average of 65%,
while Umri sits at 41%.

**The map uses real coordinates, not invented ones.** The supplied dataset
carries no geometry, so `scripts/geocode_talukas.py` resolves each taluka once
through **Nominatim** (OpenStreetMap's own geocoder, one request per second
per its usage policy) and caches the result in
`frontend/lib/taluka-coords.json` with its provenance and licence. The map is
**Leaflet with OpenStreetMap tiles**; circle **area** is proportional to the
case count, so the radius scales with the square root — sizing radius directly
by value makes twice the cases look four times as bad.

These are centroids from a place search, not administrative boundaries, and
the page says so. A taluka that fails to geocode is listed as unplaced rather
than nudged onto a nearby spot: a marker in the wrong place is worse than a
missing one. All 16 resolved on the supplied data. A ranked-list view of the
same figures sits behind a toggle, and the table below carries the exact
numbers.

Two privacy rules are enforced in the aggregation, not in the UI:

- **Granularity stops at taluka.** Localities never leave the backend here,
  because a locality plus a sensitive category can identify a household. A
  test asserts no locality name appears anywhere in the response.
- **Small sensitive cells are suppressed** below `ANALYTICS_MIN_CELL_SIZE`
  (default 3). A single identity-hiding case in one taluka is a disclosure,
  not a statistic, so it is reported as `suppressed` rather than counted.

The chart colour was chosen by running the palette validator rather than by
eye, and that caught a flaw in the existing palette: signal amber and the old
signal red were only 13.2 ΔE apart for normal vision (floor is 15) while
appearing side by side on queue rows. The red is now `#DE4F5E`, at 20.6 ΔE.
Bars use one colour for every taluka: a darker-where-bigger ramp would
double-encode bar length on nominal categories.

## The weakest link, and what was done about it

The eight hard rules all trust one thing: **the category**. The sensitive
guard asks "is this category sensitive?" — so if the classifier files a
sparking live wire as *footpath damage*, the guard never fires. That is the
single most dangerous failure mode in the system, and it is not hypothetical.

Measured on 20 hand-written complaints whose wording appears nowhere in the
supplied history (`python scripts/eval_intake.py --novel`):

| Measure | Offline, no API key |
|---|---|
| Exact category | 60% |
| Acceptable category | 65% |
| Mean confidence | 0.376 |
| Routed to a human instead of auto-resolved | **100%** |

Two of the misses were sensitive cases classified as routine: a live wire read
as footpath damage, and child labour read as a school-infrastructure issue.

> Leave-one-out over the supplied history scores 100%, and that number is
> worthless: the history is templated, so every held-out row still has
> near-duplicates of its own category in the index. The novel set is the
> honest estimate.

**Two independent precautionary signals** now withhold automation when a case
may be sensitive even though its chosen category is not:

1. **Retrieved neighbours** filed under a sensitive category. Strong with
   semantic embeddings; blind with the offline lexical fallback, because
   "live wire sparking" shares no words with "damaged electrical cable
   hanging close to the public path".
2. **Distinctive wording from the master's sensitive categories.** Needs no
   embedding at all. The vocabulary is derived from whatever the loaded CSV
   calls its sensitive categories, and only terms used by at most two
   categories count — so "wire" and "harassment" fire while "public" and
   "service" do not. Swap the CSV and the vocabulary follows.

Both are **one-directional by construction**: they can only turn
AUTO_RESOLVE into HUMAN_QUEUE. No quantity of evidence can unlock an
automated closure, which is what keeps rule 1 intact. A test asserts a queued
case is never promoted.

Verified: a model that is 99% confident the live wire is footpath damage is
still held for human review, while a genuine pothole and a genuine water leak
at the same confidence still auto-resolve.

## Proving it to someone who will not run your tests

`/compliance` executes every hard-rule probe against the live policy module
and the category table loaded at that moment, and reports what actually
happened — including the refusal text. It is not a screenshot of a passing
test run; press the button and the probes execute again. Weaken a guard and a
row goes red.

`/officer/{reference_no}` shows the agent hand-offs as a ledger, rebuilt
server-side from the decision record, audit log and dispatch log the run
itself wrote. It works with no Langfuse keys and no network, and shows the
Langfuse link alongside when tracing is configured. A stage the run never
reached is reported as "not reached" rather than drawn as if it succeeded.

## Demo scenarios

```bash
cd backend && python scripts/seed_scenario_1_routine.py
```

```bash
cd backend && python scripts/seed_scenario_2_sensitive.py
```

Each script runs the real pipeline, prints the category, the policy rule, the
retrieved evidence, the resulting status and the audit trail, asserts its
expected outcome, and exits non-zero if that outcome does not hold. Scenario 2
additionally attempts an automated closure so the refusal is visible.

```bash
cd backend && python scripts/seed_scenario_3_duplicates_sla.py
```

Scenario 3 files three reports of one burst pipeline, groups them into a single
incident while leaving all three grievances intact, then runs the SLA scan at a
moment **before** the deadline and raises an escalation alert with its evidence.

## Languages and voice

The citizen desk accepts Marathi, Hindi and English, in text or speech, and
the whole interface switches with the language — not just the input box.

- **Voice** records in the browser and posts the audio to
  `POST /api/intake/transcribe`, which calls the configured transcription
  model (`STT_MODEL`, default `gpt-transcribe`; `whisper-1` and
  `gpt-4o-transcribe` are marked deprecated in the current SDK). The language
  is passed explicitly rather than detected, which materially improves Marathi
  and Hindi accuracy.
- **Without `OPENAI_API_KEY`**, transcription returns **503 rather than a
  fabricated transcript** — a wrong transcript would become a filed
  grievance — and the voice button is disabled with the reason on hover.
- **Marathi and Hindi text without an API key** cannot be classified, because
  the offline classifier has no translation. The chat says exactly that, in
  the citizen's own language, and the case goes to a human officer. It does
  not guess a category.

Location is extracted deterministically as a backstop: the 16 talukas and 51
localities are read from the loaded CSVs and matched against what the citizen
wrote, so routing does not depend on the model noticing a place name. This is
also what lets a one-word follow-up answer ("Mukhed Town") complete a draft.

## Running without an API key

The system runs end to end with no `OPENAI_API_KEY`:

- Classification falls back to an offline lexical classifier that scores the
  complaint against the loaded category master. It has no hardcoded categories
  either, so it still follows a swapped CSV, and it reports a low confidence on
  ambiguous input, which routes those cases to human review.
- Embeddings fall back to a deterministic local hash embedding.
- Tracing is disabled and the pipeline is unaffected.

Retrieval always reports which method produced the evidence — `pgvector-knn`,
`in-memory-cosine` or `keyword-overlap` — so lexical matches are never
presented as semantic ones.

## Architecture

```
Citizen (Next.js chat)        Officer (Next.js queue)
         |                             |
         +------------ FastAPI --------+
                          |
     +--------------------+--------------------+
     |                    |                    |
 Agent pipeline      Policy guards         Loaders
 (LangGraph)         (deterministic)       (CSV -> DB)
     |                    |                    |
     +----------- Postgres + pgvector ---------+
                          |
            Langfuse traces | n8n webhooks (mock)
```

Pipeline: `Intake -> Retrieval -> Policy -> Decision -> Action`, traced in
Langfuse with span names `intake.draft`, `retrieval.topk`, `policy.gate`,
`decision.route`, `action.execute`.

Retrieval supplies evidence; it never decides an outcome. The Policy gate reads
the category master, not the retrieved cases.

### Schema

Configuration, replaced from CSV on load: `category_master`,
`department_directory`, `grievance_history` (+ embedding).

Runtime: `grievance`, `citizen_contact`, `intake_session`, `decision`,
`audit_log`, `incident`, `sla_alert`, `notification`.

Two deliberate choices:

- **Identity lives in its own table.** `citizen_contact` is separate so
  department-facing queries simply never join it. Masking is then a property of
  the data model, not only of the serializer.
- **Policy flags are not trusted from the ticket.** `sla_days` and `sla_due_at`
  are snapshotted at creation so the citizen-facing promise does not move, but
  enforcement always re-reads `category_master`. A category that becomes
  Sensitive after a ticket was opened immediately stops being auto-closable.

### Dataset notes that shaped the build

- All three CSVs are UTF-8 **with BOM**; they are read as `utf-8-sig`.
- Booleans are `True`/`False` strings and are parsed strictly — `"TRUE"`, `"1"`
  and `""` raise rather than defaulting to `False`.
- `jurisdiction_mapping` is one cell with a prose prefix and a
  semicolon-separated taluka list; the 16 talukas exist nowhere else.
- `D009` is in the directory but no category routes to it. Reported as a
  warning, not an error.
- 65% of closed historical cases exceeded their configured SLA, and two
  category/department pairs have fewer than 8 closed samples. The SLA predictor
  reports risk with its sample size rather than a bare binary.
- The history is entirely English; Marathi and Hindi intake is demonstrated with
  purpose-built fixtures, and retrieval embeds the normalised English draft so
  cross-lingual matching does not depend on the embedding model's Marathi.
