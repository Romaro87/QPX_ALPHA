#!/usr/bin/env python3
"""Build research-only staged Post-Ex event inputs without running replay."""

from pathlib import Path

from qpx_bot.research.top100_dividend_adapter import write_adapter_dataset


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "research_data" / "qpx_top100_dividend_actions_v1"
OUTPUT = (
    ROOT / "research_data" / "qpx_top100_post_ex_event_inputs_v1"
    / "post_ex_event_inputs.json"
)


if __name__ == "__main__":
    result = write_adapter_dataset(SOURCE, OUTPUT)
    print(f"Adapter output: {OUTPUT}")
    print(f"Source events: {result['source_event_count']}")
    print(
        "Ordinary structurally eligible: "
        f"{result['ordinary_post_ex_structurally_eligible_count']}"
    )
    print(f"Output fingerprint: {result['adapter_output_fingerprint']}")
