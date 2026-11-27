# MiroFish trader adapter

A small authenticated HTTP shim in front of the MiroFish backend. It speaks the
contract `deviecall-design/mirofish-trader` already uses
(`app/lib/mirofish-client.ts`):

| Route | Returns |
| --- | --- |
| `POST /api/simulation/start` `{"seed_material": "..."}` | `202 {"simulation_id", "status": "pending", "cached": false}` right away (or `200` with `cached: true` for an in-flight or recently finished run of the same seed) |
| `GET /api/simulation/<id>/status` | `{"status": "pending" \| "running" \| "completed" \| "failed", "progress", "stage", "error"?}` |
| `GET /api/simulation/<id>/result` | `{"bias": -1..1, "conviction": 0..1, "detail": {...}}`; `409` until completed |

## Security

- **Every request on every path** needs `Authorization: Bearer <MIROFISH_API_KEY>`
  (constant-time compare). Anything else gets `401`. With no key configured the
  adapter fails closed (`503`) and refuses to start.
- The upstream Flask backend has no auth of its own. Keep it on `127.0.0.1:5001`
  and only ever expose the adapter (default `127.0.0.1:5002`) through a tunnel.
- Request bodies are capped at 64 KB and seeds at 20,000 characters.

## What a run does

ontology → Zep graph build → create → prepare (profiles + config) → start with
capped rounds → wait → read the agents' actions → distil into bias and conviction.
The report agent is skipped (the trader only needs the two numbers). Distillation
is one LLM call that scores each post's stance, with a keyword fallback; the
aggregate is the same formula as the trader's persona council.

Jobs run one at a time in a background thread, are persisted to
`adapter_state/jobs.json`, and are de-duplicated and cached by a hash of the seed.

## Settings (environment or the repo-root `.env`)

| Var | Default | Notes |
| --- | --- | --- |
| `MIROFISH_API_KEY` | — | required; long random bearer token |
| `MIROFISH_BACKEND_URL` | `http://127.0.0.1:5001` | upstream backend |
| `ADAPTER_HOST` / `ADAPTER_PORT` | `127.0.0.1` / `5002` | |
| `ADAPTER_MAX_ROUNDS` | `OASIS_DEFAULT_MAX_ROUNDS` or 10 | cost knob |
| `ADAPTER_PLATFORM` | `reddit` | `reddit`, `twitter` or `parallel` (about 2x calls) |
| `ADAPTER_MAX_RUNS_PER_DAY` | 20 | `429` above this; 0 disables |
| `ADAPTER_CACHE_TTL_S` | 21600 | reuse a finished result for the same seed |
| `ADAPTER_JOB_TIMEOUT_S` | 10800 | |
| `ADAPTER_DISTILL` | `llm` | `llm` or `lexicon` (no LLM call) |
| `ADAPTER_DISTILL_MODEL` | `LLM_MODEL_NAME` | |

## Run (Mac Mini)

```bash
cd ~/mirofish-oasis/backend && caffeinate -dimsu uv run python run.py      # backend, 127.0.0.1:5001
cd ~/mirofish-oasis && caffeinate -dimsu backend/.venv/bin/python -m adapter # adapter, 127.0.0.1:5002
```

## Tests

```bash
cd ~/mirofish-oasis && backend/.venv/bin/python -m pytest adapter/tests -q
```

`adapter/tests/test_auth.py` checks that every route (including unknown paths and
upstream paths) returns 401 for missing, empty, wrong, truncated, extended and
non-Bearer credentials, that nothing gets queued, and that the adapter fails closed with no key.

Licence: this adapter lives in the AGPL-3.0 MiroFish fork and is reached over HTTP.
