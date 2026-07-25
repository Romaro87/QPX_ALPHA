from pathlib import Path

ROOT = Path("/storage/emulated/0/QPX_ALPHA")

folders = [
    "legacy",
    "legacy/generators",
    "legacy/experiments",
    "legacy/reports",
    "legacy/backups",
    "legacy/runtime",
    "legacy/databases",
    "legacy/archived_projects",
]

for folder in folders:
    (ROOT / folder).mkdir(parents=True, exist_ok=True)

print("=" * 60)
print("QPX_ALPHA Repository Consolidation")
print("=" * 60)

print()
print("Created:")

for folder in folders:
    print(" ✓", folder)

print()
print("Repository ready for consolidation.")