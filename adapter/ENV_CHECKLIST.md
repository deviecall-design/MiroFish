# .env checklist (Damien adds the values himself)

The backend reads the **repo-root** `.env` (`~/mirofish-oasis/.env`, see
`backend/app/config.py`), not `backend/.env`. The adapter reads the same file.

```env
# LLM via OpenRouter
LLM_API_KEY=            # OpenRouter key (secret)
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL_NAME=qwen/qwen-plus

# Zep Cloud (free plan)
ZEP_API_KEY=            # secret

# Backend: local only, no debug
FLASK_HOST=127.0.0.1
FLASK_PORT=5001
FLASK_DEBUG=false
OASIS_DEFAULT_MAX_ROUNDS=10

# Adapter
MIROFISH_API_KEY=       # long random bearer token (secret), e.g. from: openssl rand -hex 32
```

Before any run: set a hard OpenRouter credit limit (about A$10 a month) on the key.
