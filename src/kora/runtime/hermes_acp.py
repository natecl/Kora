"""Persistent Hermes transport over the Agent Client Protocol (ACP).

ACP gives Kora a supported session, event, steering, and permission interface
without importing Hermes's private Python internals. Kora remains the authority:
the ACP client denies every runtime permission request unless an explicit Kora
resolver selects one of the offered options.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

import acp
import acp.schema as schema

from kora import __version__
from kora._workspace import (
    WorkspaceIdentity,
    descriptor_cwd_kwargs,
)
from kora.runtime.contracts import (
    RuntimeContractError,
    RuntimeJob,
    RuntimeResult,
    RuntimeStatus,
)
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


@asynccontextmanager
async def _spawn_descriptor_bound_agent_process(
    client: Any,
    executable: str,
    *arguments: str,
    workspace_identity: WorkspaceIdentity,
    environment: Mapping[str, str],
    before_spawn: Callable[[], object] | None = None,
) -> AsyncIterator[tuple[Any, asyncio.subprocess.Process]]:
    """Spawn ACP with a descriptor-bound cwd and bounded handle lifetime."""

    with workspace_identity.open_descriptor() as descriptor:
        spawn_kwargs = descriptor_cwd_kwargs(descriptor)
        if before_spawn is not None:
            before_spawn()
        process = await asyncio.create_subprocess_exec(
            executable,
            *arguments,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=dict(environment),
            **spawn_kwargs,
        )

    if process.stdin is None or process.stdout is None:
        process.kill()
        await process.wait()
        raise RuntimeError("descriptor-bound ACP launch requires stdio pipes")

    connection: Any | None = None
    try:
        connection = acp.connect_to_agent(
            client,
            process.stdin,
            process.stdout,
            use_unstable_protocol=True,
        )
        yield connection, process
    finally:
        if connection is not None:
            with suppress(Exception):
                await connection.close()
        if process.stdin is not None:
            try:
                process.stdin.write_eof()
            except (AttributeError, OSError, RuntimeError):
                process.stdin.close()
            with suppress(Exception):
                await process.stdin.drain()
            with suppress(Exception):
                process.stdin.close()
            with suppress(Exception):
                await process.stdin.wait_closed()
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()


class _KoraACPClient:
    """Minimal ACP client that collects semantic events and gates permissions."""

    def __init__(
        self,
        permission_resolver: PermissionResolver | None = None,
        live_fence_validator: Callable[[], object] | None = None,
    ) -> None:
        self.permission_resolver = permission_resolver
        self.live_fence_validator = live_fence_validator
        self.message_chunks: list[str] = []
        self.tool_events: list[dict[str, str | None]] = []
        self.connection: Any = None

    def _validate_effect_boundary(self) -> None:
        if self.live_fence_validator is None:
            return
        try:
            result = self.live_fence_validator()
        except Exception as exc:  # noqa: BLE001 - ACP authority boundary
            if isinstance(exc, RuntimeContractError):
                raise
            raise RuntimeContractError(
                "live Kora execution fence validation failed"
            ) from exc
        if result is False:
            raise RuntimeContractError(
                "live Kora execution fence validation was rejected"
            )

    def on_connect(self, conn: Any) -> None:
        self.connection = conn

    async def request_permission(
        self,
        options: list[schema.PermissionOption],
        session_id: str,
        tool_call: schema.ToolCallUpdate,
        **_: Any,
    ) -> schema.RequestPermissionResponse:
        self._validate_effect_boundary()
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
        self._validate_effect_boundary()
        raise PermissionError("Kora ACP client filesystem access is disabled")

    async def write_text_file(self, **_: Any) -> schema.WriteTextFileResponse | None:
        self._validate_effect_boundary()
        raise PermissionError("Kora ACP client filesystem access is disabled")

    async def create_terminal(self, **_: Any) -> schema.CreateTerminalResponse:
        self._validate_effect_boundary()
        raise PermissionError("Kora ACP client terminal access is disabled")

    async def terminal_output(self, **_: Any) -> schema.TerminalOutputResponse:
        self._validate_effect_boundary()
        raise PermissionError("Kora ACP client terminal access is disabled")

    async def release_terminal(self, **_: Any) -> schema.ReleaseTerminalResponse | None:
        self._validate_effect_boundary()
        raise PermissionError("Kora ACP client terminal access is disabled")

    async def wait_for_terminal_exit(
        self, **_: Any
    ) -> schema.WaitForTerminalExitResponse:
        self._validate_effect_boundary()
        raise PermissionError("Kora ACP client terminal access is disabled")

    async def kill_terminal(self, **_: Any) -> schema.KillTerminalResponse | None:
        self._validate_effect_boundary()
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
        workspace_identity = job._workspace_identity
        if not isinstance(workspace_identity, WorkspaceIdentity):
            raise RuntimeError("Workspace identity is unavailable for ACP launch")
        executable = self._resolve_executable()
        prompt = self._build_prompt(job)
        client = _KoraACPClient(
            self.permission_resolver,
            live_fence_validator=job.validate_execution_fence,
        )

        environment = self._build_environment()
        environment["HERMES_ACP_SKIP_CONFIGURED_MCP"] = "1"
        session_id = job.session_id

        try:
            # Keep the structural and live checks adjacent to ACP process
            # creation; setup-time validation cannot close a stop/wait race.
            job.validate_execution_fence()
            async with asyncio.timeout(job.timeout_seconds):
                async with _spawn_descriptor_bound_agent_process(
                    client,
                    executable,
                    "acp",
                    workspace_identity=workspace_identity,
                    environment=environment,
                    before_spawn=job.validate_execution_fence,
                ) as (connection, _process):
                    job.validate_execution_fence()
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
                        job.validate_execution_fence()
                        await connection.load_session(
                            cwd=str(workspace),
                            session_id=job.session_id,
                            mcp_servers=[],
                        )
                    else:
                        job.validate_execution_fence()
                        session = await connection.new_session(
                            cwd=str(workspace),
                            mcp_servers=[],
                        )
                        session_id = self._validate_identifier(
                            session.session_id, "session_id"
                        )
                    job.validate_execution_fence()
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
