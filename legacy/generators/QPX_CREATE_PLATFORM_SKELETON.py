from pathlib import Path

ROOT = Path("/storage/emulated/0/QPX_ALPHA")

directories = [
    "app",
    "core",
    "core/services",
    "core/events",
    "core/config",
    "engines",
    "engines/data",
    "engines/features",
    "engines/signals",
    "engines/portfolio",
    "engines/risk",
    "engines/backtest",
    "engines/execution",
    "analytics",
    "strategies",
    "dashboard",
    "ai",
    "reports",
    "tests",
    "archive",
    "config",
    "logs",
    "data",
]

for directory in directories:
    path = ROOT / directory
    path.mkdir(parents=True, exist_ok=True)

    init = path / "__init__.py"
    if directory not in ["logs", "data", "archive"] and not init.exists():
        init.write_text('"""QPX_ALPHA Package"""\n', encoding="utf-8")

print("=" * 60)
print("QPX_ALPHA Platform Skeleton Created")
print("=" * 60)

for d in directories:
    print(d)