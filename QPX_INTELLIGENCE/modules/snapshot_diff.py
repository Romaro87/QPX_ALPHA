"""
============================================================
QPX SNAPSHOT DIFFERENCE ENGINE
Version 1.0
============================================================

Compares the two newest snapshots.

Outputs

snapshot_diff.json
SNAPSHOT_DIFFERENCE.md
"""

import json
import os
from datetime import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

SNAPSHOTS = os.path.join(
    ROOT,
    "QPX_INTELLIGENCE",
    "snapshots"
)

OUTPUT = os.path.join(
    ROOT,
    "QPX_INTELLIGENCE",
    "output"
)


class SnapshotDiff:

    def load(self, folder, filename):

        path = os.path.join(folder, filename)

        if not os.path.exists(path):
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def newest(self):

        folders = []

        for f in os.listdir(SNAPSHOTS):

            if f == "LATEST":
                continue

            full = os.path.join(SNAPSHOTS, f)

            if os.path.isdir(full):
                folders.append(f)

        folders.sort()

        if len(folders) < 2:
            return None, None

        return (
            os.path.join(SNAPSHOTS, folders[-2]),
            os.path.join(SNAPSHOTS, folders[-1])
        )

    def compare_numbers(self, old, new):

        return {
            "old": old,
            "new": new,
            "change": new - old
        }

    def run(self):

        previous, current = self.newest()

        if previous is None:

            print("Need at least two snapshots.")
            return

        old_arch = self.load(
            previous,
            "architecture.json"
        )

        new_arch = self.load(
            current,
            "architecture.json"
        )

        old_dep = self.load(
            previous,
            "dependency_analysis.json"
        )

        new_dep = self.load(
            current,
            "dependency_analysis.json"
        )

        old_summary = old_arch.get(
            "summary",
            {}
        )

        new_summary = new_arch.get(
            "summary",
            {}
        )

        diff = {

            "generated":
                datetime.now().isoformat(),

            "previous":
                os.path.basename(previous),

            "current":
                os.path.basename(current),

            "architecture": {

                "python_files":
                    self.compare_numbers(
                        old_summary.get(
                            "python_files",
                            0
                        ),
                        new_summary.get(
                            "python_files",
                            0
                        )
                    ),

                "classes":
                    self.compare_numbers(
                        old_summary.get(
                            "classes",
                            0
                        ),
                        new_summary.get(
                            "classes",
                            0
                        )
                    ),

                "functions":
                    self.compare_numbers(
                        old_summary.get(
                            "functions",
                            0
                        ),
                        new_summary.get(
                            "functions",
                            0
                        )
                    ),

                "imports":
                    self.compare_numbers(
                        old_summary.get(
                            "imports",
                            0
                        ),
                        new_summary.get(
                            "imports",
                            0
                        )
                    ),

                "entry_points":
                    self.compare_numbers(
                        old_summary.get(
                            "entry_points",
                            0
                        ),
                        new_summary.get(
                            "entry_points",
                            0
                        )
                    )

            },

            "dependency": {

                "orphans":
                    self.compare_numbers(

                        old_dep.get(
                            "summary",
                            {}
                        ).get(
                            "orphans",
                            0
                        ),

                        new_dep.get(
                            "summary",
                            {}
                        ).get(
                            "orphans",
                            0
                        )

                    ),

                "dependencies":
                    self.compare_numbers(

                        old_dep.get(
                            "summary",
                            {}
                        ).get(
                            "dependencies",
                            0
                        ),

                        new_dep.get(
                            "summary",
                            {}
                        ).get(
                            "dependencies",
                            0
                        )

                    )

            }

        }

        with open(

            os.path.join(
                OUTPUT,
                "snapshot_diff.json"
            ),

            "w",

            encoding="utf-8"

        ) as f:

            json.dump(
                diff,
                f,
                indent=4
            )

        report = os.path.join(
            OUTPUT,
            "SNAPSHOT_DIFFERENCE.md"
        )

        with open(
            report,
            "w",
            encoding="utf-8"
        ) as f:

            f.write("# Snapshot Difference\n\n")

            f.write(
                f"Previous: {diff['previous']}\n\n"
            )

            f.write(
                f"Current: {diff['current']}\n\n"
            )

            f.write("## Architecture\n\n")

            for k, v in diff["architecture"].items():

                sign = "+" if v["change"] >= 0 else ""

                f.write(
                    f"- {k}: "
                    f"{v['old']} → {v['new']} "
                    f"({sign}{v['change']})\n"
                )

            f.write("\n")

            f.write("## Dependencies\n\n")

            for k, v in diff["dependency"].items():

                sign = "+" if v["change"] >= 0 else ""

                f.write(
                    f"- {k}: "
                    f"{v['old']} → {v['new']} "
                    f"({sign}{v['change']})\n"
                )

            f.write("\n")

            f.write("## AI Summary\n\n")

            if diff["architecture"]["python_files"]["change"] > 0:

                f.write(
                    "- New Python modules were added.\n"
                )

            if diff["architecture"]["functions"]["change"] > 0:

                f.write(
                    "- Function count increased.\n"
                )

            if diff["dependency"]["dependencies"]["change"] > 0:

                f.write(
                    "- Dependency graph expanded.\n"
                )

            if diff["dependency"]["orphans"]["change"] > 0:

                f.write(
                    "- Review newly unreferenced module candidates.\n"
                )

            if all(
                item["change"] == 0
                for item in diff["architecture"].values()
            ):

                f.write(
                    "- No architectural changes detected.\n"
                )

        print("=" * 60)
        print("QPX SNAPSHOT DIFFERENCE ENGINE")
        print("=" * 60)
        print()
        print("Previous :", diff["previous"])
        print("Current  :", diff["current"])
        print()
        print("Output")
        print(os.path.join(OUTPUT, "snapshot_diff.json"))
        print(report)
        print()
        print("STATUS : COMPLETE")


if __name__ == "__main__":
    SnapshotDiff().run()