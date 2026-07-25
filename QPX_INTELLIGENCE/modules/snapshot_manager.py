"""
============================================================
QPX SNAPSHOT MANAGER
Version 1.0
============================================================

Creates immutable project snapshots.

Each snapshot contains the complete AI context package.

Output

QPX_INTELLIGENCE/

    snapshots/

        2026-07-25_121500/

            architecture.json
            dependency_analysis.json
            history.json
            recommendations.json
            metrics.json
            manifest.json
            project_graph.json
            PROJECT_SUMMARY.md
            README_CONTEXT.md
            QPX_AI_BOOTSTRAP.md
            qpx_context.py
            snapshot_manifest.json
"""

import os
import json
import shutil
import hashlib
from datetime import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

OUTPUT = os.path.join(
    ROOT,
    "QPX_INTELLIGENCE",
    "output"
)

SNAPSHOTS = os.path.join(
    ROOT,
    "QPX_INTELLIGENCE",
    "snapshots"
)


class SnapshotManager:

    def __init__(self):

        os.makedirs(SNAPSHOTS, exist_ok=True)

        self.timestamp = datetime.now().strftime(
            "%Y-%m-%d_%H%M%S"
        )

        self.snapshot = os.path.join(
            SNAPSHOTS,
            self.timestamp
        )

        os.makedirs(self.snapshot)

        self.manifest = {

            "timestamp": self.timestamp,

            "created": datetime.now().isoformat(),

            "files": [],

            "total_files": 0,

            "total_size": 0,

            "sha256": {}
        }

    def checksum(self, filename):

        h = hashlib.sha256()

        with open(filename, "rb") as f:

            while True:

                chunk = f.read(65536)

                if not chunk:
                    break

                h.update(chunk)

        return h.hexdigest()

    def copy_output(self):

        for file in sorted(os.listdir(OUTPUT)):

            source = os.path.join(
                OUTPUT,
                file
            )

            if not os.path.isfile(source):
                continue

            destination = os.path.join(
                self.snapshot,
                file
            )

            shutil.copy2(
                source,
                destination
            )

            size = os.path.getsize(destination)

            self.manifest["files"].append(file)

            self.manifest["total_files"] += 1

            self.manifest["total_size"] += size

            self.manifest["sha256"][file] = \
                self.checksum(destination)

    def save_manifest(self):

        outfile = os.path.join(
            self.snapshot,
            "snapshot_manifest.json"
        )

        with open(outfile, "w",
                  encoding="utf-8") as f:

            json.dump(
                self.manifest,
                f,
                indent=4
            )

    def latest(self):

        latest = os.path.join(
            SNAPSHOTS,
            "LATEST"
        )

        if os.path.exists(latest):

            if os.path.isdir(latest):

                shutil.rmtree(latest)

            else:

                os.remove(latest)

        shutil.copytree(
            self.snapshot,
            latest
        )

    def run(self):

        self.copy_output()

        self.save_manifest()

        self.latest()

        return self.snapshot


def main():

    print()

    print("=" * 60)
    print("QPX SNAPSHOT MANAGER")
    print("=" * 60)

    manager = SnapshotManager()

    folder = manager.run()

    print()

    print("Snapshot")

    print(folder)

    print()

    print("Files")

    print(manager.manifest["total_files"])

    print()

    print("Size")

    print(manager.manifest["total_size"])

    print()

    print("STATUS : COMPLETE")


if __name__ == "__main__":
    main()