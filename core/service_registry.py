"""
QPX_ALPHA Service Registry
Sprint 4 Milestone 4
"""

from typing import Dict


class ServiceRegistry:
    """Simple singleton-style service registry."""

    def __init__(self):
        self._services: Dict[str, object] = {}

    def register(self, name: str, service):
        self._services[name] = service

    def unregister(self, name: str):
        self._services.pop(name, None)

    def get(self, name: str):
        return self._services.get(name)

    def exists(self, name: str):
        return name in self._services

    def list_services(self):
        return sorted(self._services.keys())

    def count(self):
        return len(self._services)


registry = ServiceRegistry()
