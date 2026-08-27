from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import acp.schema as schema

from kora.runtime import Capability, HermesACPRuntimeAdapter, RuntimeJob
from kora.runtime.hermes_acp import ACPPermissionRequest, _KoraACPClient


def _job(workspace: Path, **overrides: object) -> RuntimeJob:
    values: dict[str, object] = {
        "mission_id": "mission-123",
        "task_id": "task-456",
        "objective": "Continue the approved narrow slice.",
        "instructions": "Return evidence without broadening the goal.",
        "workspace": workspace,
        "capabilities": frozenset({Capability.NETWORK_READ}),
    }
    values.update(overrides)
    return RuntimeJob(**values)


class _FakeACPContext:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    async def __aenter__(self) -> tuple[object, object]:
        return self.connection, object()

    async def __aexit__(self, *_: object) -> bool:
        return False


def _fake_connection(*, new_session_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        initialize=AsyncMock(),
        new_session=AsyncMock(
            return_value=SimpleNamespace(session_id=new_session_id)
        ),
        load_session=AsyncMock(return_value=SimpleNamespace()),
        prompt=AsyncMock(
            return_value=SimpleNamespace(stop_reason="end_turn", usage=None)
        ),
    )


class KoraACPClientTests(unittest.TestCase):
    def test_denies_permission_by_default(self) -> None:
        client = _KoraACPClient()
        response = asyncio.run(
            client.request_permission(
                options=[
                    schema.PermissionOption(
                        optionId="allow_once",
                        kind="allow_once",
                        name="Allow once",
                    )
                ],
                session_id="session-1",
                tool_call=schema.ToolCallUpdate(
                    toolCallId="tool-1",
                    title="Write a file",
                    kind="edit",
                    status="pending",
                ),
            )
        )
        self.assertIsInstance(response.outcome, schema.DeniedOutcome)

    def test_allows_only_resolver_selected_option(self) -> None:
        seen: list[ACPPermissionRequest] = []

        def resolve(request: ACPPermissionRequest) -> str | None:
            seen.append(request)
            return "allow_once"

        client = _KoraACPClient(resolve)
        response = asyncio.run(
            client.request_permission(
                options=[
                    schema.PermissionOption(
                        optionId="allow_once",
                        kind="allow_once",
                        name="Allow once",
                    ),
                    schema.PermissionOption(
                        optionId="allow_always",
                        kind="allow_always",
                        name="Always allow",
                    ),
                ],
                session_id="session-1",
                tool_call=schema.ToolCallUpdate(
                    toolCallId="tool-1",
                    title="Write a file",
                    kind="edit",
                    status="pending",
                ),
            )
        )
        self.assertIsInstance(response.outcome, schema.AllowedOutcome)
        self.assertEqual(response.outcome.option_id, "allow_once")
        self.assertEqual(seen[0].kind, "edit")

    def test_collects_only_agent_message_text(self) -> None:
        client = _KoraACPClient()
        asyncio.run(
            client.session_update(
                session_id="session-1",
                update=schema.AgentThoughtChunk(
                    sessionUpdate="agent_thought_chunk",
                    content=schema.TextContentBlock(type="text", text="hidden"),
                ),
            )
        )
        asyncio.run(
            client.session_update(
                session_id="session-1",
                update=schema.AgentMessageChunk(
                    sessionUpdate="agent_message_chunk",
                    content=schema.TextContentBlock(
                        type="text", text="KORA_TASK_COMPLETE"
                    ),
                ),
            )
        )
        self.assertEqual(client.final_text, "KORA_TASK_COMPLETE")


class HermesACPRuntimeAdapterTests(unittest.TestCase):
    def test_uses_new_session_and_returns_server_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            connection = _fake_connection(new_session_id="new-session-123")
            adapter = HermesACPRuntimeAdapter(
                cloud_root=root,
                hermes_executable="/usr/bin/true",
            )
            with patch(
                "kora.runtime.hermes_acp.acp.spawn_agent_process",
                return_value=_FakeACPContext(connection),
            ) as spawn:
                result = asyncio.run(adapter.run_async(_job(root)))

            spawn.assert_called_once()
            connection.new_session.assert_awaited_once_with(
                cwd=str(root.resolve()),
                mcp_servers=[],
            )
            connection.load_session.assert_not_awaited()
            connection.prompt.assert_awaited_once()
            self.assertEqual(
                connection.prompt.await_args.kwargs["session_id"],
                "new-session-123",
            )
            self.assertEqual(result.session_id, "new-session-123")

    def test_loads_requested_session_and_returns_its_id(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            connection = _fake_connection(new_session_id="unused-new-session")
            adapter = HermesACPRuntimeAdapter(
                cloud_root=root,
                hermes_executable="/usr/bin/true",
            )
            with patch(
                "kora.runtime.hermes_acp.acp.spawn_agent_process",
                return_value=_FakeACPContext(connection),
            ):
                result = asyncio.run(
                    adapter.run_async(
                        _job(root, session_id="resume-session-123")
                    )
                )

            connection.load_session.assert_awaited_once_with(
                cwd=str(root.resolve()),
                session_id="resume-session-123",
                mcp_servers=[],
            )
            connection.new_session.assert_not_awaited()
            self.assertEqual(
                connection.prompt.await_args.kwargs["session_id"],
                "resume-session-123",
            )
            self.assertEqual(result.session_id, "resume-session-123")

    def test_uses_restricted_environment_and_forces_acp_mcp_skip(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            connection = _fake_connection(new_session_id="new-session-123")
            adapter = HermesACPRuntimeAdapter(
                cloud_root=root,
                hermes_executable="/usr/bin/true",
                environment={
                    "HERMES_API_KEY": "explicit-secret",
                    "HERMES_ACP_SKIP_CONFIGURED_MCP": "0",
                },
            )
            with patch.dict(
                os.environ,
                {"KORA_HOST_SECRET": "must-not-be-inherited"},
                clear=False,
            ):
                with patch(
                    "kora.runtime.hermes_acp.acp.spawn_agent_process",
                    return_value=_FakeACPContext(connection),
                ) as spawn:
                    asyncio.run(adapter.run_async(_job(root)))

            environment = spawn.call_args.kwargs["env"]
            self.assertNotIn("KORA_HOST_SECRET", environment)
            self.assertEqual(environment["HERMES_API_KEY"], "explicit-secret")
            self.assertEqual(
                environment["HERMES_ACP_SKIP_CONFIGURED_MCP"],
                "1",
            )


if __name__ == "__main__":
    unittest.main()
