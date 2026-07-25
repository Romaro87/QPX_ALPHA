from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")
CORE = ROOT / "core"

registry = textwrap.dedent("""
from core.logger import get_logger

logger = get_logger(__name__)


class ServiceRegistry:

    def __init__(self):
        self._services = {}

    def register(self, name: str, service):
        self._services[name] = service
        logger.info(f"Registered service: {name}")

    def get(self, name: str):
        return self._services.get(name)

    def list_services(self):
        return sorted(self._services.keys())

    def startup_report(self):
        return {
            name: "REGISTERED"
            for name in self.list_services()
        }


registry = ServiceRegistry()
""").strip()

(CORE / "registry.py").write_text(registry + "\n", encoding="utf-8")

test = textwrap.dedent("""
from core.registry import registry
from core.config import settings
from core.health import health

registry.register("config", settings)
registry.register("health", health)

print()

print("Registered Services")

print("-------------------")

for name in registry.list_services():
    print(name)

print()

print(registry.startup_report())
""").strip()

(ROOT / "tests" / "test_registry.py").write_text(test + "\n", encoding="utf-8")

print("=" * 60)
print("Service Registry Created")
print("=" * 60)
print("Run:")
print("python -m tests.test_registry")