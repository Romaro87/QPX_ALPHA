from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from qpx_bot.shadow_matrix.forward import build_cycle_payload, dispatch_cycle, flush_pending_event
from qpx_bot.shadow_matrix.registry import load_registry


class Store:
    def __init__(self): self.events = []
    def event(self, kind, details): self.events.append((kind, details)); return True
    def save(self, state): self.saved = state


class ShadowForwardAdapterTests(unittest.TestCase):
    def test_registry_and_shared_compact_snapshot(self):
        registry = load_registry()
        self.assertEqual(len(registry.configurations), 45)
        symbols = tuple(f"S{i:03d}" for i in range(100))
        now = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)
        bar = {"start": now, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}
        payload = build_cycle_payload(
            symbols=symbols, histories={s: [bar] for s in symbols},
            indices={s: {now: 0} for s in symbols}, indicators={},
            bar_time=now, observed_at=now, vix=20,
            contract={"feed": "iex", "universe_manifest_fingerprint": "u", "contract_fingerprint": "c"},
        )
        self.assertEqual(len(payload["symbols"]), 100)
        self.assertEqual(len(payload["observations"]), 100)
        state = {"cash": 1400.0, "qdte_shares": 0, "qdte_cost": 0.0, "positions": {}}
        store = Store(); summary = dispatch_cycle(state, store, payload=payload, observed_at=now)
        self.assertEqual(summary["dispatch_count"], 45)
        self.assertEqual(summary["healthy_count"], 45)
        self.assertIn("shadow_matrix_event_pending", state)
        flush_pending_event(state, store)
        self.assertEqual(store.events[0][0], "SHADOW_MATRIX_DECISION_CYCLE")

    def test_shadow_checkpoint_restores_without_provider_access(self):
        now = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)
        symbols = tuple(f"S{i:03d}" for i in range(100))
        payload = {"symbols": list(symbols), "decision_bar": now.isoformat(), "semantic_contract_fingerprint": "c"}
        state = {"cash": 1400.0, "qdte_shares": 0, "qdte_cost": 0.0, "positions": {}}
        dispatch_cycle(state, Store(), payload=payload, observed_at=now)
        state2 = {"cash": 1400.0, "qdte_shares": 0, "qdte_cost": 0.0, "positions": {}, "shadow_matrix_checkpoint": state["shadow_matrix_checkpoint"]}
        result = dispatch_cycle(state2, Store(), payload={**payload, "decision_bar": (now.replace(minute=15)).isoformat()}, observed_at=now.replace(minute=15))
        self.assertEqual(result["event_sequence"], 2)


if __name__ == "__main__": unittest.main()
