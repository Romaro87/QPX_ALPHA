from __future__ import annotations

import getpass
import json
import os
from pathlib import Path


path = Path.home() / ".config" / "qpx" / "alpaca.json"

print()
print("QPX — ALPACA API KEY SETUP")
print("=" * 50)
print("Your keys are stored outside the Git repository.")
print("Do NOT paste them into ChatGPT.")
print()

key_id = input("Alpaca API Key ID: ").strip()
secret_key = getpass.getpass("Alpaca Secret Key: ").strip()

if not key_id:
    raise SystemExit("API Key ID cannot be empty.")

if not secret_key:
    raise SystemExit("Secret Key cannot be empty.")

path.parent.mkdir(parents=True, exist_ok=True)

path.write_text(
    json.dumps(
        {
            "key_id": key_id,
            "secret_key": secret_key,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

try:
    os.chmod(path, 0o600)
except OSError:
    pass

print()
print("Alpaca credentials saved.")
print(f"Location: {path}")
print("The credentials were NOT stored inside QPX_ALPHA.")
