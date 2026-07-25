from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")

CORE = ROOT / "core"

health = textwrap.dedent("""
from pathlib import Path

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)


class HealthService:

    def __init__(self):
        self.results = {}

    def check_directory(self, name, path: Path):
        ok = path.exists()

        self.results[name] = ok

        logger.info(f"{name}: {'PASS' if ok else 'FAIL'}")

    def run(self):

        self.results = {}

        self.check_directory("Data Directory", settings.DATA_DIR)

        self.check_directory("Log Directory", settings.LOG_DIR)

        self.check_directory("Reports Directory", settings.REPORT_DIR)

        self.check_directory("Cache Directory", settings.CACHE_DIR)

        return self.results

    def healthy(self):
        return all(self.results.values())


health = HealthService()
""").strip()

(CORE / "health.py").write_text(
    health + "\n",
    encoding="utf-8"
)

test = textwrap.dedent("""
from core.health import health

results = health.run()

print()

print("=" * 50)

print("QPX_ALPHA HEALTH REPORT")

print("=" * 50)

for item, status in results.items():
    print(f"{item:<25} {'PASS' if status else 'FAIL'}")

print()

print("Overall:",
      "HEALTHY" if health.healthy() else "UNHEALTHY")
""").strip()

(ROOT / "tests" / "test_health.py").write_text(
    test + "\n",
    encoding="utf-8"
)

print("=" * 60)
print("Health Service Created")
print("=" * 60)