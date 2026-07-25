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
