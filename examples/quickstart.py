"""Run a local example tool through an Asqav guard.

Set ASQAV_API_KEY, then run python examples/quickstart.py. Provider setup
and signing use the Asqav API; the weather result is a local fixture.
"""

from __future__ import annotations

import asyncio
import os

from autogen_core import CancellationToken
from autogen_core.tools import FunctionTool

from asqav_autogen import AsqavGuardrail, attach


def get_weather(city: str) -> str:
    """A trivial example tool."""
    return f"Weather in {city}: sunny, 21C"


def build_guarded_tool(guardrail: AsqavGuardrail) -> object:
    """Wrap the weather tool so each call routes through the guardrail."""
    weather_tool = FunctionTool(get_weather, description="Get the weather", name="get_weather")
    return attach(weather_tool, guardrail)


async def main() -> None:
    guardrail = AsqavGuardrail(api_key=os.environ["ASQAV_API_KEY"], agent_name="autogen-quickstart")
    tool = build_guarded_tool(guardrail)
    result = await tool.run_json({"city": "Lisbon"}, CancellationToken())
    print("tool result:", result)
    print("asqav receipt:", guardrail.last_receipt_id)


if __name__ == "__main__":
    asyncio.run(main())
