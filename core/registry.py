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
