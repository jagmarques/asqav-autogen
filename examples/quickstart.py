"""Quickstart: sign one guarded AutoGen tool call with asqav.

Run it against api.asqav.com:

    ASQAV_API_KEY=sk_... python examples/quickstart.py

The five lines from import to a signed receipt live in main() below. The
helpers are importable so a test can drive the same path under a mock.
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
