#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from qpx_bot.ml_historical_acquisition import DEFAULT_ROOT, status

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=DEFAULT_ROOT); args = parser.parse_args()
    print(json.dumps(status(args.root), indent=2, sort_keys=True)); return 0

if __name__ == "__main__":
    raise SystemExit(main())
