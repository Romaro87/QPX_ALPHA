from dashboard import dashboard_module
from core.module_registry import module_registry

module_registry.register(dashboard_module)

modules = module_registry.list_modules()

assert len(modules) == 1

assert modules[0].id == "dashboard"

print("Module Registry PASS")
