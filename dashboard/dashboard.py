from core.module_registry import Module

def run():

    print()

    print("=" * 50)

    print("QPX_ALPHA Dashboard")

    print("=" * 50)

    print()

    print("Platform is healthy.")

    input("\nPress ENTER to return...")


dashboard_module = Module(
    id="dashboard",
    title="Dashboard",
    description="Platform overview",
    callback=run
)
