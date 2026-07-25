"""
Command Router

Routes scaffold commands to registered handlers.
"""


class CommandRouter:

    def __init__(self):
        self._commands = {}

    def register(self, name, handler):
        self._commands[name] = handler

    def execute(self, name, *args):

        if name not in self._commands:
            raise ValueError(f"Unknown command: {name}")

        return self._commands[name](*args)

    def commands(self):
        return sorted(self._commands.keys())

    def count(self):
        return len(self._commands)


router = CommandRouter()
