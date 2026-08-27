"""Developer CLI for the initial Hermes integration spike."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from kora.mission import MissionService
from kora.runtime import (
    Capability,
    HermesACPRuntimeAdapter,
    HermesRuntimeAdapter,
    IsolationMode,
    RuntimeJob,
)


def _json_default(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kora-hermes-spike")
    parser.add_argument(
        "--hermes",
        default="hermes",
        help="Hermes executable to invoke (default: hermes on PATH).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health", help="Check Hermes and ACP availability.")

    smoke = subparsers.add_parser(
        "smoke", help="Run a safe, read-only Kora runtime job."
    )
    smoke.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace and cloud-root boundary for the smoke test.",
    )
    acp_smoke = subparsers.add_parser(
        "acp-smoke", help="Run the same job through persistent Hermes ACP."
    )
    acp_smoke.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace and cloud-root boundary for the ACP smoke test.",
    )

    mission_create = subparsers.add_parser(
        "mission-create", help="Create a proposed persistent mission."
    )
    mission_create.add_argument(
        "--database", type=Path, default=Path("kora-missions.sqlite3")
    )
    mission_create.add_argument("--title", required=True)
    mission_create.add_argument("--objective", required=True)
    mission_create.add_argument("--definition-of-done", required=True)
    mission_create.add_argument(
        "--exclude",
        dest="exclusions",
        action="append",
        default=[],
        help="An explicit mission exclusion; may be repeated.",
    )

    mission_status = subparsers.add_parser(
        "mission-status", help="Show a persistent mission and its task state."
    )
    mission_status.add_argument("mission_id")
    mission_status.add_argument(
        "--database", type=Path, default=Path("kora-missions.sqlite3")
    )
    return parser


def main() -> None:
    args = _parser().parse_args()

    if args.command == "mission-create":
        with MissionService(args.database) as service:
            mission = service.create_mission(
                title=args.title,
                objective=args.objective,
                definition_of_done=args.definition_of_done,
                exclusions=args.exclusions,
            )
        print(json.dumps(asdict(mission), default=_json_default, indent=2))
        return

    if args.command == "mission-status":
        with MissionService(args.database) as service:
            report = service.get_status(args.mission_id)
        payload = {
            "mission": asdict(report.mission),
            "tasks": [asdict(task) for task in report.tasks],
            "open_escalations": [asdict(item) for item in report.open_escalations],
            "next_task": asdict(report.next_task) if report.next_task else None,
        }
        print(json.dumps(payload, default=_json_default, indent=2))
        return

    workspace = getattr(args, "workspace", Path.cwd()).expanduser().resolve()
    adapter_class = (
        HermesACPRuntimeAdapter if args.command == "acp-smoke" else HermesRuntimeAdapter
    )
    adapter = adapter_class(
        cloud_root=workspace,
        hermes_executable=args.hermes,
    )

    if args.command == "health":
        print(json.dumps(asdict(adapter.check_health()), indent=2))
        return

    job = RuntimeJob(
        mission_id="kora-harness-spike",
        task_id="structured-smoke",
        objective="Verify that Kora can submit a mission-scoped job to Hermes.",
        instructions=(
            "Do not call tools. Reply with exactly two lines: "
            "KORA_TASK_COMPLETE followed by adapter contract verified."
        ),
        workspace=workspace,
        toolsets=("search",),
        capabilities=frozenset({Capability.NETWORK_READ}),
        isolation=IsolationMode.READ_ONLY,
        timeout_seconds=60,
    )
    result = adapter.run(job)
    print(json.dumps(asdict(result), indent=2))
