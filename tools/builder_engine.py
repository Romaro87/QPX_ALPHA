"""
Reusable Builder Engine
"""

from pathlib import Path


class BuilderEngine:

    def __init__(self):
        self.root = Path.cwd()

    def write(self, relative_path, contents):

        path = self.root / relative_path

        path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        path.write_text(
            contents.strip() + "\n",
            encoding="utf-8"
        )

        print(f"Created {relative_path}")

    def exists(self, relative_path):

        return (self.root / relative_path).exists()
