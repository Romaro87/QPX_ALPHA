from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")

CONFIG = ROOT / "core" / "config"
CONFIG.mkdir(parents=True, exist_ok=True)

(CONFIG / "__init__.py").write_text(
    "from .settings import settings\n",
    encoding="utf-8"
)

settings = textwrap.dedent("""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:

    PROJECT_NAME: str = "QPX_ALPHA"

    VERSION: str = "2.0"

    ROOT: Path = Path(__file__).resolve().parents[2]

    DATA_DIR: Path = ROOT / "data"

    LOG_DIR: Path = ROOT / "logs"

    REPORT_DIR: Path = ROOT / "reports"

    CACHE_DIR: Path = ROOT / "cache"

    AI_ENABLED: bool = True

    PAPER_TRADING: bool = True

    DEFAULT_PROVIDER: str = "yfinance"

    LOG_LEVEL: str = "INFO"


settings = Settings()
""").strip()

(CONFIG / "settings.py").write_text(
    settings + "\n",
    encoding="utf-8"
)

print("=" * 60)
print("Configuration Service Created")
print("=" * 60)
print(CONFIG)