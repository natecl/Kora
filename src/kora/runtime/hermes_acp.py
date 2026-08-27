"""Persistent Hermes transport over the Agent Client Protocol (ACP).

ACP gives Kora a supported session, event, steering, and permission interface
without importing Hermes's private Python internals. Kora remains the authority:
the ACP client denies every runtime permission request unless an explicit Kora
resolver selects one of the offered options.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import acp
import acp.schema as schema

from kora import __version__
from kora.runtime.contracts import RuntimeJob, RuntimeResult, RuntimeStatus
from kora.runtime.hermes import HermesRuntimeAdapter


@dataclass(frozen=True, slots=True)
class ACPPermissionRequest:
    """Sanitized permission request presented to Kora's authority engine."""

    session_id: str
    tool_call_id: str
    title: str
    kind: str | None
    option_ids: tuple[str, ...]


PermissionResolver = Callable[[ACPPermissionRequest], str | None]


class _KoraACPClient:
    """Minimal ACP client that collects semantic events and gates permissions."""

    def __init__(self, permission_resolver: PermissionResolver | None = None) -> None:
        self.permission_resolver = permission_resolver
        self.message_chunks: list[str] = []
        self.tool_events: list[dict[str, str | None]] = []
        self.connection: Any = None

    def on_connect(self, conn: Any) -> None:
        self.connection = conn

    async def request_permission(
        self,
        options: list[schema.PermissionOption],
        session_id: str,
        tool_call: schema.ToolCallUpdate,
        **_: Any,
    ) -> schema.RequestPermissionResponse:
        option_ids = tuple(option.option_id for option in options)
        request = ACPPermissionRequest(
            session_id=session_id,
            tool_call_id=tool_call.tool_call_id,
            title=tool_call.title or "Hermes runtime action",
            kind=tool_call.kind,
            option_ids=option_ids,
        )
        selected = (
            self.permission_resolver(request)
            if self.permission_resolver is not None
            else None
        )
        if selected in option_ids:
            return schema.RequestPermissionResponse(
                outcome=schema.AllowedOutcome(
                    optionId=selected,
                    outcome="selected",
                )
            )
        return schema.RequestPermissionResponse(
            outcome=schema.DeniedOutcome(outcome="cancelled")
        )

    async def session_update(
        self,
        session_id: str,
        update: Any,
        **_: Any,
    ) -> None:
        del session_id
        if isinstance(update, schema.AgentMessageChunk):
            content = update.content
            if isinstance(content, schema.TextContentBlock):
                self.message_chunks.append(content.text)
            return

        if isinstance(update, (schema.ToolCallStart, schema.ToolCallProgress)):
            self.tool_events.append(
                {
                    "tool_call_id": update.tool_call_id,
                    "title": update.title,
                    "kind": update.kind,
                    "status": update.status,
                }
            )

    async def read_text_file(self, **_: Any) -> schema.ReadTextFileResponse:
        raise PermissionError("Kora ACP client filesystem access is disabled")

    async def write_text_file(self, **_: Any) -> schema.WriteTextFileResponse | None:
        raise PermissionError("Kora ACP client filesystem access is disabled")

    async def create_terminal(self, **_: Any) -> schema.CreateTerminalResponse:
        raise PermissionError("Kora ACP client terminal access is disabled")

    async def terminal_output(self, **_: Any) -> schema.TerminalOutputResponse:
        raise PermissionError("Kora ACP client terminal access is disabled")

    async def release_terminal(self, **_: Any) -> schema.ReleaseTerminalResponse | None:
        raise PermissionError("Kora ACP client terminal access is disabled")

    async def wait_for_terminal_exit(
        self, **_: Any
    ) -> schema.WaitForTerminalExitResponse:
        raise PermissionError("Kora ACP client terminal access is disabled")

    async def kill_terminal(self, **_: Any) -> schema.KillTerminalResponse | None:
        raise PermissionError("Kora ACP client terminal access is disabled")

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        del method, params
        return {}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        del method, params

    @property
    def final_text(self) -> str:
        return "".join(self.message_chunks).strip()


class HermesACPRuntimeAdapter(HermesRuntimeAdapter):
    """Run a Kora job in a persistent Hermes ACP session."""

    def __init__(
        self,
        *,
        cloud_root: Path,
        hermes_executable: str | Path = "hermes",
        environment: Mapping[str, str] | None = None,
        permission_resolver: PermissionResolver | None = None,
    ) -> None:
        super().__init__(
            cloud_root=cloud_root,
            hermes_executable=hermes_executable,
            environment=environment,
        )
        self.permission_resolver = permission_resolver

    def run(self, job: RuntimeJob) -> RuntimeResult:
        """Synchronous convenience wrapper for non-async control-plane callers."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(job))
        raise RuntimeError("Use await run_async(job) from an active event loop")

    async def run_async(self, job: RuntimeJob) -> RuntimeResult:
        workspace = self._validate_job(job)
        executable = self._resolve_executable()
        prompt = self._build_prompt(job)
        client = _KoraACPClient(self.permission_resolver)

        environment = self._build_environment()
        environment["HERMES_ACP_SKIP_CONFIGURED_MCP"] = "1"
        session_id = job.session_id

        try:
            async with asyncio.timeout(job.timeout_seconds):
                async with acp.spawn_agent_process(
                    client,
                    executable,
                    "acp",
                    cwd=workspace,
                    env=environment,
                    transport_kwargs={"stderr": asyncio.subprocess.DEVNULL},
                    use_unstable_protocol=True,
                ) as (connection, _process):
                    await connection.initialize(
                        protocol_version=acp.PROTOCOL_VERSION,
                        client_capabilities=schema.ClientCapabilities(
                            fs=schema.FileSystemCapabilities(
                                readTextFile=False,
                                writeTextFile=False,
                            ),
                            terminal=False,
                        ),
                        client_info=schema.Implementation(
                            name="kora-control-plane",
                            title="Kora",
                            version=__version__,
                        ),
                    )
                    if job.session_id is not None:
                        # ACP 0.9 acknowledges a loaded session without
                        # repeating its already-known session ID.
                        await connection.load_session(
                            cwd=str(workspace),
                            session_id=job.session_id,
                            mcp_servers=[],
                        )
                    else:
                        session = await connection.new_session(
                            cwd=str(workspace),
                            mcp_servers=[],
                        )
                        session_id = self._validate_identifier(
                            session.session_id, "session_id"
                        )
                    response = await connection.prompt(
                        session_id=session_id,
                        prompt=[
                            schema.TextContentBlock(
                                type="text",
                                text=prompt,
                            )
                        ],
                    )
        except TimeoutError:
            return RuntimeResult(
                mission_id=job.mission_id,
                task_id=job.task_id,
                status=RuntimeStatus.FAILED,
                response="Hermes ACP runtime timed out.",
                exit_code=124,
                session_id=session_id,
            )
        except Exception as exc:
            return RuntimeResult(
                mission_id=job.mission_id,
                task_id=job.task_id,
                status=RuntimeStatus.FAILED,
                response=f"Hermes ACP runtime failed: {type(exc).__name__}",
                exit_code=1,
                session_id=session_id,
            )

        final_text = client.final_text
        status = self._status_for(0, final_text)
        if response.stop_reason in {"refusal", "cancelled"}:
            status = RuntimeStatus.FAILED

        input_tokens: int | None = None
        output_tokens: int | None = None
        usage = response.usage
        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
        total_tokens = None
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            total_tokens = input_tokens + output_tokens

        return RuntimeResult(
            mission_id=job.mission_id,
            task_id=job.task_id,
            status=status,
            response=final_text,
            exit_code=0,
            total_tokens=total_tokens,
            session_id=session_id,
        )
