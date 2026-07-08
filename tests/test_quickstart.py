"""The examples/quickstart.py path works under a mocked asqav transport."""

from __future__ import annotations

from autogen_core import CancellationToken

from asqav_autogen import AsqavGuardrail


async def test_quickstart_build_and_run(fake_agent):
    import quickstart  # from examples/, put on sys.path by conftest

    guard = AsqavGuardrail(agent_name="autogen-quickstart")
    tool = quickstart.build_guarded_tool(guard)
    out = await tool.run_json({"city": "Lisbon"}, CancellationToken())

    assert "Lisbon" in str(out)
    assert guard.last_receipt_id == "sig_test123"
