"""Adapter settings, read from the environment (the fork's root .env is loaded too).

Nothing secret is ever logged or returned. MIROFISH_API_KEY must be set or every
route refuses with 503 (fail closed).
"""

import os

from dotenv import load_dotenv

_ROOT_ENV = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_ROOT_ENV):
    load_dotenv(_ROOT_ENV, override=False)


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


class Settings:
    def __init__(self) -> None:
        self.api_key = (os.environ.get("MIROFISH_API_KEY") or "").strip()
        self.backend_url = os.environ.get("MIROFISH_BACKEND_URL", "http://127.0.0.1:5001").rstrip("/")
        self.host = os.environ.get("ADAPTER_HOST", "127.0.0.1")
        self.port = _int("ADAPTER_PORT", 5002, 1, 65535)
        # Cost knobs: rounds cap and platform. "reddit" runs one platform (about half
        # the LLM calls of "parallel").
        self.max_rounds = _int("ADAPTER_MAX_ROUNDS", _int("OASIS_DEFAULT_MAX_ROUNDS", 10, 1, 500), 1, 500)
        platform = os.environ.get("ADAPTER_PLATFORM", "reddit").lower()
        self.platform = platform if platform in ("reddit", "twitter", "parallel") else "reddit"
        self.max_runs_per_day = _int("ADAPTER_MAX_RUNS_PER_DAY", 20, 0, 10_000)
        self.cache_ttl_s = _int("ADAPTER_CACHE_TTL_S", 6 * 3600, 0, 30 * 86400)
        self.job_timeout_s = _int("ADAPTER_JOB_TIMEOUT_S", 3 * 3600, 60, 48 * 3600)
        self.poll_s = _int("ADAPTER_POLL_S", 10, 1, 600)
        self.distill = os.environ.get("ADAPTER_DISTILL", "llm").lower()  # llm | lexicon
        self.state_dir = os.environ.get(
            "ADAPTER_STATE_DIR", os.path.join(os.path.dirname(__file__), "..", "adapter_state")
        )
        # LLM settings for the single distillation call (same provider as the backend).
        self.llm_api_key = os.environ.get("LLM_API_KEY") or ""
        self.llm_base_url = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
        self.llm_model = os.environ.get("ADAPTER_DISTILL_MODEL") or os.environ.get("LLM_MODEL_NAME", "qwen/qwen-plus")
