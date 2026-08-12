"""Shadow Matrix V1 isolated research orchestration foundation."""

from qpx_bot.shadow_matrix.checkpoint import ShadowCheckpointError, restore_checkpoint, serialize_checkpoint
from qpx_bot.shadow_matrix.engine import ShadowMatrixEngine, acknowledge_event
from qpx_bot.shadow_matrix.models import (
    AcceleratorSnapshot,
    DecisionRecord,
    DivergenceRecord,
    QuarantineRecord,
    RecoveryAuthorization,
    MarketEvent,
    PositionEntrySnapshot,
    ShadowConfiguration,
    ShadowRole,
)
from qpx_bot.shadow_matrix.registry import ShadowRegistry, load_registry
from qpx_bot.shadow_matrix.metrics import ShadowMetrics
from qpx_bot.shadow_matrix.state import ShadowPosition, ShadowState, PyramidAdditionSnapshot

__all__ = (
    "AcceleratorSnapshot", "DecisionRecord", "DivergenceRecord", "MarketEvent",
    "PositionEntrySnapshot", "ShadowConfiguration", "ShadowMatrixEngine",
    "QuarantineRecord", "RecoveryAuthorization", "ShadowCheckpointError", "ShadowMetrics",
    "PyramidAdditionSnapshot", "ShadowPosition", "ShadowRegistry", "ShadowRole", "ShadowState",
    "acknowledge_event", "load_registry", "restore_checkpoint", "serialize_checkpoint",
)
