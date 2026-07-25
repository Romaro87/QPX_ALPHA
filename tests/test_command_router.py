from tools.command_router import CommandRouter

router = CommandRouter()

router.register(
    "hello",
    lambda: "world"
)

assert router.count() == 1
assert router.execute("hello") == "world"

print("Command Router PASS")
