from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")

CORE = ROOT / "core"
DASHBOARD = ROOT / "dashboard"

DASHBOARD.mkdir(exist_ok=True)

module_registry = textwrap.dedent("""
from dataclasses import dataclass
from typing import Callable


@dataclass
class Module:

    id: str
    title: str
    description: str
    callback: Callable


class ModuleRegistry:

    def __init__(self):
        self._modules = {}

    def register(self, module: Module):
        self._modules[module.id] = module

    def list_modules(self):
        return list(self._modules.values())

    def get(self, module_id):
        return self._modules.get(module_id)


module_registry = ModuleRegistry()
""").strip()

(CORE / "module_registry.py").write_text(
    module_registry + "\n",
    encoding="utf-8"
)

dashboard = textwrap.dedent("""
from core.module_registry import Module

def run():

    print()

    print("=" * 50)

    print("QPX_ALPHA Dashboard")

    print("=" * 50)

    print()

    print("Platform is healthy.")

    input("\\nPress ENTER to return...")


dashboard_module = Module(
    id="dashboard",
    title="Dashboard",
    description="Platform overview",
    callback=run
)
""").strip()

(DASHBOARD / "__init__.py").write_text(
    "from .dashboard import dashboard_module\n",
    encoding="utf-8"
)

(DASHBOARD / "dashboard.py").write_text(
    dashboard + "\n",
    encoding="utf-8"
)

test = textwrap.dedent("""
from dashboard import dashboard_module
from core.module_registry import module_registry

module_registry.register(dashboard_module)

modules = module_registry.list_modules()

assert len(modules) == 1

assert modules[0].id == "dashboard"

print("Module Registry PASS")
""").strip()

(ROOT / "tests" / "test_module_registry.py").write_text(
    test + "\n",
    encoding="utf-8"
)

print("=" * 60)
print("Module Registry Created")
print("=" * 60)
print("Run:")
print("python -m tests.test_module_registry")