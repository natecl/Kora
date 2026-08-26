from __future__ import annotations

import asyncio
import unittest

import acp.schema as schema

from kora.runtime.hermes_acp import ACPPermissionRequest, _KoraACPClient


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


if __name__ == "__main__":
    unittest.main()
