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
