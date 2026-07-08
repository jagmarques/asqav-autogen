"""asqav-autogen: an AutoGen GuardrailProvider backed by asqav signed receipts.

Standalone package. It implements the GuardrailProvider protocol proposed in
microsoft/autogen#7405 and needs no change to autogen itself.
"""

from .attach import GuardedTool, GuardedWorkbench, attach
from .guardrail import AsqavGuardrail, PolicyFn, PolicyVerdict
from .protocol import Decision, GuardrailProvider, GuardrailResult

__all__ = [
    "AsqavGuardrail",
    "Decision",
    "GuardedTool",
    "GuardedWorkbench",
    "GuardrailProvider",
    "GuardrailResult",
    "PolicyFn",
    "PolicyVerdict",
    "attach",
]

__version__ = "0.1.0"
