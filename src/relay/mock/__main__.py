"""Run the mock model service locally: python -m relay.mock."""

import argparse
import os

import uvicorn

from .config import scenario_config
from .service import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The Relay deterministic mock model service")
    parser.add_argument("--scenario", default=os.environ.get("MOCK_SCENARIO", "normal"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args(argv)
    config = scenario_config(args.scenario)
    app = create_app(config)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
