"""Start the public synthetic-data demo from any working directory."""

from argparse import ArgumentParser
from pathlib import Path
import os
import sys

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main() -> None:
    parser = ArgumentParser(description="Run the opinion Agent with synthetic public event cards")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    os.environ.setdefault(
        "EVENT_CARDS_PATH", str(PROJECT_ROOT / "examples" / "demo_event_cards.jsonl")
    )
    uvicorn.run("opinion_agent.api:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
