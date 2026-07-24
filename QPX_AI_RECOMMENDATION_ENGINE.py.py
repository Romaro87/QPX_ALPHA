#!/usr/bin/env python3
"""
=============================================================
QPX AI RECOMMENDATION ENGINE
Part 1

Reads

    scanner.json
    architecture.json
    history.json

Produces

    recommendations.json

Future Parts

Part 2
    Architecture Analysis

Part 3
    Dependency Analysis

Part 4
    AI Recommendation Generation

Part 5
    ChatGPT Bootstrap Generation

=============================================================
"""

import os
import json
import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

CONTEXT = os.path.join(ROOT, "QPX_CONTEXT")

SCANNER = os.path.join(CONTEXT, "scanner.json")

ARCH = os.path.join(CONTEXT, "architecture.json")

HISTORY = os.path.join(CONTEXT, "history.json")

OUTPUT = os.path.join(
    CONTEXT,
    "recommendations.json"
)


class RecommendationEngine:

    def __init__(self):

        self.scanner = self.load(SCANNER)

        self.architecture = self.load(ARCH)

        self.history = self.load(HISTORY)

        self.recommendations = []

        self.ai_guidance = []

        self.project_health = {}

    def load(self, path):

        with open(path, "r", encoding="utf-8") as f:

            return json.load(f)

    def add(
        self,
        category,
        priority,
        confidence,
        title,
        evidence,
        recommendation
    ):

        self.recommendations.append({

            "category": category,

            "priority": priority,

            "confidence": confidence,

            "title": title,

            "evidence": evidence,

            "recommendation": recommendation

        })

    def add_guidance(self, text):

        self.ai_guidance.append(text)

    def analyze_statistics(self):

        stats = self.scanner["statistics"]

        duplicates = len(
            self.scanner["duplicates"]
        )

        backups = stats["backups"]

        python = stats["python"]

        self.project_health = {

            "python_modules": python,

            "duplicate_modules": duplicates,

            "backup_files": backups,

            "reports": stats["reports"]

        }

        if duplicates > 50:

            self.add(

                category="Architecture",

                priority="High",

                confidence=0.99,

                title="Large Duplicate Module Count",

                evidence=[

                    f"{duplicates} duplicate filenames detected."

                ],

                recommendation=(

                    "Identify canonical implementations "

                    "and archive obsolete duplicates."

                )

            )

        if backups > 20:

            self.add(

                category="Maintenance",

                priority="Medium",

                confidence=0.97,

                title="Large Backup Inventory",

                evidence=[

                    f"{backups} backup files discovered."

                ],

                recommendation=(

                    "Move historical backups into "

                    "a dedicated archive folder."

                )

            )

    def analyze_architecture(self):

        repairs = len(

            self.architecture["repair_modules"]

        )

        entry = len(

            self.architecture["entry_points"]

        )

        if repairs > 20:

            self.add(

                "Architecture",

                "Medium",

                0.96,

                "Repair Framework Opportunity",

                [

                    f"{repairs} repair utilities found."

                ],

                (

                    "Create a reusable repair "

                    "framework shared by all "

                    "repair scripts."

                )

            )

        if entry > 50:

            self.add(

                "Architecture",

                "Medium",

                0.92,

                "High Entry Point Count",

                [

                    f"{entry} executable modules."

                ],

                (

                    "Separate user-facing entry "

                    "points from developer utilities."

                )

            )

    def analyze_history(self):

        health = self.history["project_health"]

        self.add(

            "Project Status",

            "Info",

            0.99,

            "Current Health",

            [

                f'Overall health: {health["overall"]}'

            ],

            (

                "Continue maintaining automated "

                "validation after major changes."

            )

        )

    def build_guidance(self):

        self.add_guidance(

            "Prefer extending existing modules."

        )

        self.add_guidance(

            "Avoid duplicate functionality."

        )

        self.add_guidance(

            "Preserve backward compatibility."

        )

        self.add_guidance(

            "Validate every repair."

        )

        self.add_guidance(

            "Regenerate qpx_context.py after "

            "major milestones."

        )

    def save(self):

        report = {

            "generated":

                datetime.datetime.now().isoformat(),

            "project_health":

                self.project_health,

            "recommendations":

                self.recommendations,

            "ai_guidance":

                self.ai_guidance

        }

        with open(

            OUTPUT,

            "w",

            encoding="utf-8"

        ) as f:

            json.dump(

                report,

                f,

                indent=4

            )

        return report

    def run(self):

        self.analyze_statistics()

        self.analyze_architecture()

        self.analyze_history()

        self.build_guidance()

        return self.save()


def main():

    engine = RecommendationEngine()

    report = engine.run()

    print("=" * 60)

    print("QPX AI RECOMMENDATION ENGINE")

    print("=" * 60)

    print()

    print("Recommendations")

    print(len(report["recommendations"]))

    print()

    print("AI Guidance")

    print(len(report["ai_guidance"]))

    print()

    print("Output")

    print(OUTPUT)

    print()

    print("STATUS: COMPLETE")


if __name__ == "__main__":

    main()