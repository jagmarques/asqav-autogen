"""Live end-to-end against api.asqav.com. Skips cleanly without a key."""

from __future__ import annotations

import os

import pytest
from autogen_core import CancellationToken
from autogen_core.tools import FunctionTool

from asqav_autogen import AsqavGuardrail, attach

pytestmark = pytest.mark.skipif(
    not os.environ.get("ASQAV_API_KEY"),
    reason="live e2e needs ASQAV_API_KEY",
)


async def test_live_signs_a_real_receipt():
    def get_time(zone: str) -> str:
        return f"time in {zone}"

    guard = AsqavGuardrail(api_key=os.environ["ASQAV_API_KEY"], agent_name="autogen-e2e")
    tool = attach(FunctionTool(get_time, description="time", name="get_time"), guard)
    out = await tool.run_json({"zone": "UTC"}, CancellationToken())

    assert "UTC" in str(out)
    assert guard.last_receipt_id is not None
