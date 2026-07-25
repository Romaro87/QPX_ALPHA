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
