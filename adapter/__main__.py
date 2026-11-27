"""Run: backend/.venv/bin/python -m adapter (from the repo root)."""

import logging

from .config import Settings
from .server import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = Settings()
    if not s.api_key:
        raise SystemExit("MIROFISH_API_KEY is not set; refusing to start (the adapter fails closed).")
    app = create_app(s)
    app.run(host=s.host, port=s.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
