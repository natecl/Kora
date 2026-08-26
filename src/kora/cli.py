"""Developer CLI for the initial Hermes integration spike."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from kora.runtime import (
    Capability,
    HermesACPRuntimeAdapter,
    HermesRuntimeAdapter,
    IsolationMode,
    RuntimeJob,
)


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
    return parser


def main() -> None:
    args = _parser().parse_args()
    workspace = getattr(args, "workspace", Path.cwd()).expanduser().resolve()
    adapter_class = (
        HermesACPRuntimeAdapter
        if args.command == "acp-smoke"
        else HermesRuntimeAdapter
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
