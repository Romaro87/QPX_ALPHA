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
