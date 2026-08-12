"""Shadow Matrix V1 isolated research orchestration foundation."""

from qpx_bot.shadow_matrix.engine import ShadowMatrixEngine, acknowledge_event
from qpx_bot.shadow_matrix.models import (
    AcceleratorSnapshot,
    DecisionRecord,
    MarketEvent,
    PositionEntrySnapshot,
    ShadowConfiguration,
    ShadowRole,
)
from qpx_bot.shadow_matrix.registry import ShadowRegistry, load_registry
from qpx_bot.shadow_matrix.state import ShadowPosition, ShadowState

__all__ = (
    "AcceleratorSnapshot", "DecisionRecord", "MarketEvent",
    "PositionEntrySnapshot", "ShadowConfiguration", "ShadowMatrixEngine",
    "ShadowPosition", "ShadowRegistry", "ShadowRole", "ShadowState",
    "acknowledge_event", "load_registry",
)
