from __future__ import annotations

import json
import stat
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from kora.runtime import (
    Capability,
    HermesRuntimeAdapter,
    HermesRuntimeError,
    IsolationMode,
    RuntimeJob,
    RuntimeStatus,
)


def _job(workspace: Path, **overrides: object) -> RuntimeJob:
    values: dict[str, object] = {
        "mission_id": "mission-123",
        "task_id": "task-456",
        "objective": "Build the approved narrow slice.",
        "instructions": "Return evidence without broadening the goal.",
        "workspace": workspace,
        "toolsets": ("search",),
        "capabilities": frozenset({Capability.NETWORK_READ}),
    }
    values.update(overrides)
    return RuntimeJob(**values)


class HermesRuntimeAdapterTests(unittest.TestCase):
    def test_rejects_workspace_outside_cloud_root(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as other_dir:
            adapter = HermesRuntimeAdapter(cloud_root=Path(root_dir))
            with self.assertRaisesRegex(HermesRuntimeError, "outside Kora cloud root"):
                adapter.run(_job(Path(other_dir)))

    def test_rejects_unknown_toolset(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            adapter = HermesRuntimeAdapter(cloud_root=root)
            with self.assertRaisesRegex(HermesRuntimeError, "not approved"):
                adapter.run(_job(root, toolsets=("everything",)))

    def test_rejects_missing_capability(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            adapter = HermesRuntimeAdapter(cloud_root=root)
            with self.assertRaisesRegex(HermesRuntimeError, "network.read"):
                adapter.run(_job(root, capabilities=frozenset()))

    def test_mutating_toolset_requires_cloud_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            adapter = HermesRuntimeAdapter(cloud_root=root)
            capabilities = frozenset(
                {Capability.WORKSPACE_READ, Capability.WORKSPACE_WRITE}
            )
            with self.assertRaisesRegex(HermesRuntimeError, "cloud-sandbox"):
                adapter.run(
                    _job(
                        root,
                        toolsets=("file",),
                        capabilities=capabilities,
                        isolation=IsolationMode.READ_ONLY,
                    )
                )

    def test_runs_fake_hermes_and_sanitizes_usage(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            executable = root / "fake-hermes"
            executable.write_text(
                """#!/usr/bin/env python3
import json
import pathlib
import sys

args = sys.argv[1:]
usage_path = pathlib.Path(args[args.index('--usage-file') + 1])
usage_path.write_text(json.dumps({
    'api_calls': 1,
    'total_tokens': 99,
    'estimated_cost_usd': 0.01,
    'model': 'must-stay-hidden',
    'provider': 'must-stay-hidden'
}), encoding='utf-8')
prompt = args[args.index('-z') + 1]
if 'Mission ID: mission-123' not in prompt or 'Do not create or broaden goals.' not in prompt:
    raise SystemExit(3)
print('KORA_TASK_COMPLETE')
print('Evidence: adapter contract verified.')
""",
                encoding="utf-8",
            )
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

            adapter = HermesRuntimeAdapter(
                cloud_root=root,
                hermes_executable=executable,
            )
            result = adapter.run(_job(root))

            self.assertEqual(result.status, RuntimeStatus.COMPLETED)
            self.assertEqual(result.api_calls, 1)
            self.assertEqual(result.total_tokens, 99)
            self.assertEqual(result.estimated_cost_usd, 0.01)
            serialized = json.dumps(asdict(result))
            self.assertNotIn("must-stay-hidden", serialized)
            self.assertNotIn("model", serialized)
            self.assertNotIn("provider", serialized)


if __name__ == "__main__":
    unittest.main()
