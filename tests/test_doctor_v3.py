"""
Sprint 4 Milestone 4

Doctor v3 Validation
"""

from core.service_registry import registry


def test_service_registry():

    assert registry.count() == 0

    registry.register("demo", object())

    assert registry.exists("demo")

    assert registry.count() == 1

    registry.unregister("demo")

    assert registry.count() == 0


if __name__ == "__main__":

    test_service_registry()

    print("PASS")
