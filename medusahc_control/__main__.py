from __future__ import annotations

import argparse
import logging

from .config import AppConfig
from .server import serve


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MedusaHC local control dashboard")
    parser.add_argument("--config", help="Path to JSON configuration file")
    parser.add_argument("--bind", help="Address to listen on")
    parser.add_argument("--port", type=int, help="Port to listen on")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--simulate", action="store_true", help="Use the built-in safe printer simulator")
    mode.add_argument("--live", action="store_true", help="Connect to the configured Moonraker instance")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose service logging")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = AppConfig.from_file(args.config)
    simulate = True if args.simulate else False if args.live else None
    config = config.with_overrides(bind=args.bind, port=args.port, simulate=simulate)
    serve(config)


if __name__ == "__main__":
    main()

