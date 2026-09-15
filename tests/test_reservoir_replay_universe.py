from __future__ import annotations

from pathlib import Path
import unittest

from qpx_bot.reservoir_replay_universe import build_manifest


class ReservoirReplayUniverseTests(unittest.TestCase):
    def test_asset_identity_preserves_same_symbol_and_unknown_status(self):
        root = Path(__file__).parents[1] / "research_data/qpx_ml_historical_v1"
        manifest = build_manifest(root)
        self.assertEqual(manifest["selected_count"], 31431)
        self.assertEqual(manifest["split_excluded_count"], 2044)
        self.assertTrue(all(item["provider_status"] == "UNKNOWN" for item in manifest["members"]))
        self.assertEqual(len({item["provider_asset_id"] for item in manifest["members"]}), 31431)
