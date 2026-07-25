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
