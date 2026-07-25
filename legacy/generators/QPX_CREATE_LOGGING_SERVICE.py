from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")

CORE = ROOT / "core"
LOGS = ROOT / "logs"

CORE.mkdir(exist_ok=True)
LOGS.mkdir(exist_ok=True)

logger_source = textwrap.dedent("""
from pathlib import Path
import logging

from core.config import settings

LOG_FILE = settings.LOG_DIR / "qpx_alpha.log"

settings.LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, settings.LOG_LEVEL))

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.propagate = False

    return logger
""").strip()

(CORE / "logger.py").write_text(
    logger_source + "\n",
    encoding="utf-8"
)

example = textwrap.dedent("""
from core.logger import get_logger

logger = get_logger(__name__)

logger.info("Logging service initialized successfully.")
logger.warning("Example warning.")
logger.error("Example error.")
""").strip()

(ROOT / "test_logging.py").write_text(
    example + "\n",
    encoding="utf-8"
)

print("=" * 60)
print("Logging Service Created")
print("=" * 60)
print("Created:")
print("  core/logger.py")
print("  test_logging.py")
print()
print("Run:")
print("python test_logging.py")