# TrueFit — Purpose-Driven Shopping Planner

> Current scope: PC recommendations, in Korean. Baby-products support and the English UI were removed on 2026-09-21 (see git history).

**English** · [한국어](README.ko.md)

> *"A quiet gaming PC for around ₩1,500,000."*
> TrueFit turns a goal like that into a budget-checked shopping list, with the reasons, the open checks, and what the review data actually shows — and leaves the decision to the person.

Built with the **Strands Agents SDK** for the AWS *Agents for Humans* hackathon, **Everyday Agents** track (home, money, family). MIT licensed.

## The problem

Buying for a purpose is a research chore that repeats every time: a PC build is eight parts that must fit each other (socket, power, size) and a budget. The two sources people rely on are the least trustworthy — review scores that can be gamed, and recommendation sites that hand out a number without saying why.

TrueFit is built on three refusals:

1. **No verdict without a method.** It never says a review is fake or a part is "the best". It reports what can be checked, in plain words — *"60 reviews (about 29%) were posted within the same week; for similar parts, usually only about 5% are"* — with the source figures one click away, and lets the reader decide.
2. **Numbers from code, words from the model.** Ranking, verification, budget math and every value that gets stored are computed; the language model only turns free text into structured conditions and turns stored facts into sentences.
3. **The agent proposes, the person decides.** Every recommendation is editable, every edit is a tool call on the same persisted plan, and nothing is purchased — links go to sellers.

## What it does

Category → conditions chat → recommendation → confirm → report, in one browser flow. No login is needed until you save.

| Step | What happens |
|---|---|
| **Conditions** | Chips for required fields, free text for everything else. A Strands agent turns *"quiet gaming PC, around ₩1,500,000, Elden Ring, white case if possible"* into typed, validated conditions and asks for whatever is still missing |
| **Recommendation** | The engine builds candidates per slot, filters, ranks (review observations demote, never exclude), optimizes the set, verifies it and re-searches once if confidence is low. Each item carries a reason, *before-you-buy* checks that cite a care guide, and plain-language review observations — what stands out against similar parts, never a verdict |
| **Edit by talking** | *"Swap the CPU for a cheaper one and tell me why the GPU was picked"* — a second Strands agent looks up alternatives, swaps, changes quantity or timing, or explains from stored evidence only |
| **Confirm & report** | Name, purchase date, target amount, memo; the confirmed snapshot keeps seller links and an optional target-price watch |

The engine builds **PC configurations**: it optimizes the set, then verifies it as a whole. The UI and the server speak Korean.

## Built on Strands Agents

Two agents, both opt-in, both constructed per request with the plan's current state in their tools.

| Agent | Turn | Tools | What the code enforces |
|---|---|---|---|
| **Conditions agent** — [`src/agent/conditions_agent.py`](src/agent/conditions_agent.py) | `POST /session/{id}/message` | `set_condition` · `add_extra_condition` · `clear_condition` | Only fields in `config/categories/<cat>.yaml`'s `slot_schema` exist. Enum, type, range and currency are checked in the tool; a bad value comes back as an error string the model must correct. Which fields are required and what to ask next is computed by the service after every tool call and fed back. The agent never touches the database — its patches are applied by `session_service` with the same origin tag as the rule-based path |
| **Result agent** — [`src/agent/result_agent.py`](src/agent/result_agent.py) | `POST /session/{id}/result-message` | `list_alternatives` · `swap` · `set_qty` · `set_timing` · `remove_or_restore` · `explain` | Every tool wraps an existing service call, so ownership checks and totals recomputation are the same as for the buttons. `swap` only accepts a candidate the service knows for that item — a forged id is rejected. `explain` returns the stored reason, budget share, verification issues and review observation — it cannot rate a part or a review |

```python
@tool
def set_condition(field: str, value: str) -> str:
    """Set one condition field. Amounts keep the unit the user said ("$1,500", "150만원") — code converts."""
    return draft.set(field, value)        # validates against the category schema; returns an error string on failure

agent = Agent(
    model=OpenAIModel(client_args={"api_key": OPENAI_API_KEY}, model_id=LLM_MODEL, params={"temperature": 0.2}),
    system_prompt=system_prompt(draft, text, history),   # field list, chip→value map, remaining required fields
    tools=make_tools(draft),
    messages=_history(history),
    tool_executor=SequentialToolExecutor(),                # tools mutate one draft in order
)
result = agent(text)                                       # reply for the person; draft.patches for the service
```

What is non-obvious about the setup:

- **Tools are the only way to change state, and they are validated like an API.** `"150만원"` becomes `budget_max=1,500,000`; `"purple"` for the priority field comes back as an error listing the allowed values (`performance`, `value`, `quiet`) and the model retries. Every call and its outcome is logged per turn.
- **The service, not the agent, decides what is required.** After each tool call the tool result carries the recomputed missing-field list and the next question, so the model asks exactly what the rule engine would have asked — and stops when `can_recommend` flips.
- **The result agent operates on the persisted plan, not on a transcript.** Swaps and edits go through the same code path as the UI buttons and are visible there immediately. A swap does not silently re-verify the build; the tool result says so and the agent relays it.
- **Same model, two jobs, one rule.** The engine uses the same OpenAI client for the verification-issue sentences and the explanation, but only ever with facts it computed. Turning the model off (`MOCK_MODE=1`) leaves every number unchanged and replaces the prose with placeholders.

Enable: `MOCK_MODE=0 · LLM_PROVIDER=openai · LLM_MODEL · OPENAI_API_KEY` plus `CONDITIONS_AGENT=1` / `RESULT_AGENT=1`. The model provider is one function (`_model()`); Strands' Bedrock model class drops in there. Design notes *(Korean)*: [conditions agent](docs/조건대화_에이전트_strands.md) · [result agent](docs/결과화면_에이전트_strands.md).

## How it works

![Architecture](docs/architecture.png)

<details>
<summary>Mermaid source</summary>

```mermaid
flowchart LR
  U["Person<br/>browser (Korean)"]
  subgraph App["TrueFit — FastAPI, one origin, 38 operations"]
    direction TB
    SVC["Services<br/>session · recommendation · lists · auth · reviews"]
    subgraph Strands["Strands Agents SDK"]
      CA["Conditions agent<br/>set_condition · add_extra_condition · clear_condition"]
      RA["Result agent<br/>list_alternatives · swap · set_qty · set_timing<br/>remove_or_restore · explain"]
    end
    ENG["Recommendation engine<br/>requirement → candidates → hard filter → rank<br/>→ optimize ⇄ verify → explain"]
  end
  subgraph Ev["Evidence"]
    RX["Review relation axis<br/>Amazon Reviews'23 → per-product facts"]
    CG["Care-guide RAG<br/>18 guides, in-memory embeddings"]
    MR["Manual search provider<br/>local-file, outside the RDB"]
  end
  DB[("PostgreSQL 16<br/>10 schemas · 38 tables")]
  LLM["OpenAI via Strands OpenAIModel<br/>chat + embeddings"]
  U -- "free text, chips, edits" --> SVC
  SVC --> CA
  SVC --> RA
  SVC --> ENG
  CA -- "schema-validated patches" --> SVC
  RA -- "existing service calls only" --> SVC
  ENG --> RX
  ENG --> CG
  ENG --> MR
  ENG -- "issue sentences · explanation" --> LLM
  CA --> LLM
  RA --> LLM
  SVC --> DB
```

</details>

- **Engine** (`src/engine`): intent → requirement → candidates → hard filter → rank → optimize the set ⇄ verify, re-search once below the confidence threshold → explain. `POST …/recommend` answers `202` at once; the run persists requirements, candidates, checks and explanation and `GET …/result` polls.
- **Review evidence** (`src/workers/relation_axis.py`): without reading a single review text, a batch over Amazon Reviews'23 (43.9 M reviews, 18.3 M accounts) computes per-product observations — share of reviews in the busiest 7-day window, reviewers shared with other products, one-off accounts, verified-purchase rate — each against the median of the same product category (11,457 PC-part products with ≥30 reviews; 7-day burst median 5.5%, 99th percentile 20.5%). No manipulation labels exist, so there is **no detection rate and no "cleaned" rating** ([decision 0001](docs/decisions/0001-정제-후-평점을-판정기-없이-내지-않는다.md) *(Korean)*). Observations demote a candidate in ranking; they never exclude it. On screen they are rendered from the numbers as plain Korean sentences, and when the server has no figure — review count, set confidence — nothing is shown in its place ([decision 0003](docs/decisions/0003-데모-화면에서-세트-신뢰도·회색축·표시용-리뷰-수를-뺀다.md) *(Korean)*).
- **Before-you-buy checks** (`src/rag/care_guides.py`): 18 synthetic part care guides embedded in memory at start-up; the closest passage is quoted per item.
- **Frontend** (`web/`): a React + TypeScript app served by the API on the same origin (`src/frontend_serving.py`). Sign-in, recommendation, confirm and report call the API; chat replies and the quote-check screen are still mock. Build it with `cd web && npm ci && npm run build`. The older static pages in `frontend/` still exist but their baby and English UI no longer work.

## Run it

Python **3.11** and [`uv`](https://docs.astral.sh/uv/). Configuration comes from environment variables, with `.env` as fallback (`.env.example` lists them).

**A. Console, no database, no key**

```bash
uv sync --locked
uv run python main.py computer_pass        # 8 slots, verified in one round (mock LLM, injected scores)
uv run python main.py computer_research    # score 72 → swap a candidate → 86
```

**B. Web UI with PostgreSQL**

```bash
cp .env.example .env                        # MOCK_MODE=1, agents off
docker compose up -d db
export DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit
uv run python db/setup_all.py                                # 15 migrations · domains · 51 PC parts · review summaries
uv run uvicorn src.api:app --reload --port 8000              # http://127.0.0.1:8000 · API docs at /docs
```

[`db/README.md`](db/README.md) *(Korean)* is the canonical DB guide (includes a conda route without Docker).

**C. Real model and agents** — in `.env`: `MOCK_MODE=0`, `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o-mini`, `OPENAI_API_KEY=…`, `CONDITIONS_AGENT=1`, `RESULT_AGENT=1`. Run tests with `MOCK_MODE=1 uv run python -m pytest -q`, since the suite reads `.env` too.

**D. Docker** — `docker compose up -d --build` (db + api), then `docker compose exec api python db/setup_all.py`. Set `JWT_SECRET` (the dev default is refused when `APP_ENV=production`), `COOKIE_SECURE=1` behind HTTPS, `ALLOWED_ORIGINS` only if the UI lives on another origin. The image omits `scripts/`.

## Status — measured 2026-09-14

| | Works | Not yet |
|---|---|---|
| PC | Full flow: conditions → run → reasons, checks, review observations, alternatives, swap, qty/timing, result chat → confirm → report → price watch, all persisted | Synthetic prices; compatibility is approximate (socket, power, size); a swap does not re-verify |
| Agents | Both agents verified in real sessions with `gpt-4o-mini` | Need an OpenAI key; off by default |
| Accounts | Email + password, httpOnly JWT, guest → account merge, withdrawal | Email verification and password reset deferred; `/auth/request-code`, `/auth/verify` are stubs |
| Reviews | Relation-axis facts for 25 of 51 demo parts in ranking, explanation and `GET /reviews/summary` | Review *writing* is out of demo scope; no collector for live sources yet |
| Data | 10 schemas / 38 tables, one-shot setup, RDS-compatible SQL | No live price or spec feed; notification and learning workers are stubs |

Tests on a fresh seeded DB, mock model: **747 passed, 7 failed, 6 skipped** (30 s); the 7 failures are the auth-hardening acceptance tests below. Verified by hand the same day: the PC flow over HTTP (`scripts/e2e_smoke.py`, 39/39) and the new web app up to the sign-in step.

<details>
<summary>The 7 failures, by cause</summary>

- 7 — auth-hardening acceptance tests not yet satisfied: rate limit on `email-availability`, lock-counter reset, JWT invalidation right after a password change, consent-timestamp erasure on withdrawal
- Skips: pandas not installed (2), tests that demand their own throwaway DB (6)
</details>

<details>
<summary>API surface (38 operations, <code>/docs</code>)</summary>

| Group | Operations | State |
|---|---|---|
| `/session` (14) | create, get, category, slot, message, answer, reset, spec-file, recommend (202), result, item patch, alternatives, swap, result-message | Working, no login |
| `/lists` (6) | list, rename, delete, confirm (`If-Match`), report, alert | Working; confirm/report/alert need login |
| `/auth` (10) | signup, login, logout, me (GET/PATCH), password, withdraw, email-availability | Working; request-code, verify → 501 |
| `/reviews` (5) | summary/{product_key} (engine key, summary key or ASIN); pending, part, publish | Working; build → 501 |
| `/dev` (2), `/health` | scenario runs without a DB; liveness | Guard `/dev` before public exposure |

Errors share one envelope `{"error": {"code", "message", "field"}}`. Frontend contract: [`docs/frontend_외부수정요청.md`](docs/frontend_외부수정요청.md) *(Korean)*.
</details>

## Next

3. Auth hardening the tests already describe; email verification and password reset.
4. Re-verify after a swap; real spec and price feeds; exact compatibility rules.
5. A review collector that captures author hash, posting time and variant subject from the first record ([what to capture](docs/review_collector.md) *(Korean)*), then a labeling protocol — only after that, a cleaned rating.
6. Price tracking and notifications (workers are stubs).

<details>
<summary>Repository layout</summary>

```text
main.py                       console pipeline (scenario files, mock LLM)
src/api.py, routers/          FastAPI app, 5 routers, serves frontend/
src/services/                 session · recommendation · list · auth · review · feedback
src/agent/                    Strands agents: conditions_agent.py, result_agent.py
src/engine/                   stages [1]–[6], slot_rules (keyword path), prompts, lang
src/rag/                      care_guides (in-memory RAG) · embedding · evidence_search (scenario demo)
src/repo/, src/db/, src/auth/ SQL repositories · psycopg pool · JWT/argon2/origin check
src/workers/                  review_cleanse_worker + relation_axis (batch); other workers are stubs
config/categories/            computer.yaml (slots, questions, modes)
web/                          React + TypeScript + Vite app (src/api/http = API adapter, tests/ = node tests)
frontend/                     older static pages (superseded by web/; baby and English UI no longer work)
db/                           migrate.py · 15 migrations · seed*.py · setup_all.py · README.md
scripts/                      e2e_smoke.py · Amazon'23 batch · spec scraper · review-analysis import
data/, generated/, docs/      parts list, care guides, scenarios · example outputs · specs, contracts, decisions
tests/                        pipeline · agents · HTTP flows · services · SQL/migration checks
```
</details>

## Documents & license

MIT — [`LICENSE`](LICENSE). Team documents are in Korean: [DB setup](db/README.md) · [table spec](docs/db/table_spec.md) · [schema reduction](docs/db/db_schema_reduction_proposal_2026-09-12.md) · [API contract](docs/frontend_외부수정요청.md) · [frontend rules](frontend/CLAUDE.md) · [decisions](docs/decisions/README.md) · [review analysis contract](docs/review_analysis_contract.md) · [pipeline overview](docs/pc_pipeline_overview.md) · [quickstart](docs/pc_pipeline_quickstart.md).
