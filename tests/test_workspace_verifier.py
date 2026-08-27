from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kora.mission import ArtifactKind, EvidenceKind
from kora.verification import (
    VerificationCommand,
    WorkspaceVerificationError,
    WorkspaceVerificationRequest,
    WorkspaceVerifier,
)


class WorkspaceVerifierTests(unittest.TestCase):
    def _repository(self, root: Path) -> Path:
        workspace = root / "workspace"
        workspace.mkdir()
        self._git(workspace, "init", "-q")
        (workspace / "README.md").write_text("initial\n", encoding="utf-8")
        self._git(workspace, "add", ".")
        self._git(
            workspace,
            "-c",
            "user.name=Kora Test",
            "-c",
            "user.email=kora@example.test",
            "commit",
            "-qm",
            "initial",
        )
        return workspace

    @staticmethod
    def _git(workspace: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
        )

    @staticmethod
    def _python_command(
        name: str,
        code: str,
        timeout_seconds: float = 120.0,
    ) -> VerificationCommand:
        return VerificationCommand(
            name=name,
            argv=(sys.executable, "-c", code),
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _authorized_request(
        workspace: Path,
        commands: tuple[VerificationCommand, ...],
        *,
        require_changes: bool = True,
    ) -> WorkspaceVerificationRequest:
        return WorkspaceVerificationRequest(
            workspace=workspace,
            commands=commands,
            require_changes=require_changes,
            execution_authorized=True,
            execution_capability=True,
            execution_granted=True,
            require_execution_authority=True,
            live_fence_validator=lambda: True,
        )

    def test_accepts_changed_workspace_and_returns_candidate_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self._repository(root)
            (workspace / "README.md").write_text("changed\n", encoding="utf-8")

            result = WorkspaceVerifier(cloud_root=root).verify(
                self._authorized_request(
                    workspace,
                    (self._python_command("smoke", "print('verification passed')"),),
                )
            )

            self.assertTrue(result.accepted)
            self.assertEqual([check.name for check in result.checks], ["smoke"])
            self.assertEqual(len(result.artifacts), 2)
            diff_artifact, test_artifact = result.artifacts
            self.assertEqual(diff_artifact.artifact_kind, ArtifactKind.DIFF)
            self.assertEqual(diff_artifact.evidence_kind, EvidenceKind.ARTIFACT)
            self.assertEqual(test_artifact.artifact_kind, ArtifactKind.TEST_REPORT)
            self.assertEqual(test_artifact.evidence_kind, EvidenceKind.TEST)
            self.assertEqual(
                diff_artifact.locator,
                f"workspace-diff://workspace?sha256={result.change_fingerprint}",
            )
            self.assertIn("workspace-test://workspace?command=smoke", test_artifact.locator)

    def test_stops_after_the_first_failing_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self._repository(root)
            (workspace / "README.md").write_text("changed\n", encoding="utf-8")
            should_not_run = workspace / "should-not-run"

            result = WorkspaceVerifier(cloud_root=root).verify(
                self._authorized_request(
                    workspace,
                    (
                        self._python_command("first", "print('ok')"),
                        self._python_command(
                            "failing",
                            "import sys; print('failure', file=sys.stderr); sys.exit(7)",
                        ),
                        self._python_command(
                            "after-failure",
                            (
                                "from pathlib import Path; "
                                f"Path({str(should_not_run)!r}).write_text('ran')"
                            ),
                        ),
                    ),
                )
            )

            self.assertFalse(result.accepted)
            self.assertEqual(
                [check.name for check in result.checks], ["first", "failing"]
            )
            self.assertEqual(result.checks[-1].exit_code, 7)
            self.assertIn("failure", result.checks[-1].summary)
            self.assertFalse(should_not_run.exists())
            self.assertEqual(len(result.artifacts), 3)

    def test_rejects_unchanged_workspace_before_running_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self._repository(root)
            marker = workspace / "should-not-run"

            result = WorkspaceVerifier(cloud_root=root).verify(
                self._authorized_request(
                    workspace,
                    (
                        self._python_command(
                            "unexpected",
                            f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
                        ),
                    ),
                )
            )

            self.assertFalse(result.accepted)
            self.assertIn("no changes", result.summary)
            self.assertEqual(result.checks, ())
            self.assertEqual(result.artifacts, ())
            self.assertIsNotNone(result.change_fingerprint)
            self.assertFalse(marker.exists())

    def test_can_verify_clean_workspace_when_changes_are_not_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self._repository(root)

            result = WorkspaceVerifier(cloud_root=root).verify(
                self._authorized_request(
                    workspace,
                    (self._python_command("clean-check", "print('ok')"),),
                    require_changes=False,
                )
            )

            self.assertTrue(result.accepted)
            self.assertEqual(len(result.checks), 1)
            self.assertEqual(len(result.artifacts), 1)
            self.assertEqual(
                result.artifacts[0].artifact_kind, ArtifactKind.TEST_REPORT
            )

    def test_rejects_workspace_outside_cloud_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            cloud_root = parent / "cloud"
            outside = parent / "outside"
            cloud_root.mkdir()
            outside.mkdir()

            with self.assertRaisesRegex(
                WorkspaceVerificationError, "outside Kora cloud root"
            ):
                WorkspaceVerifier(cloud_root=cloud_root).verify(
                    WorkspaceVerificationRequest(workspace=outside, commands=())
                )

    def test_rejects_git_failure_without_running_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "not-a-repository"
            workspace.mkdir()

            result = WorkspaceVerifier(cloud_root=root).verify(
                self._authorized_request(
                    workspace,
                    (self._python_command("unexpected", "raise SystemExit"),),
                    require_changes=False,
                )
            )

            self.assertFalse(result.accepted)
            self.assertIn("git", result.summary)
            self.assertIsNone(result.change_fingerprint)
            self.assertEqual(result.checks, ())
            self.assertEqual(result.artifacts, ())

    def test_does_not_inherit_host_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self._repository(root)
            (workspace / "README.md").write_text("changed\n", encoding="utf-8")
            command = self._python_command(
                "environment",
                "import os; print(os.environ.get('KORA_HOST_SECRET', '<missing>'))",
            )

            with patch.dict(
                os.environ,
                {"KORA_HOST_SECRET": "host-secret-must-not-escape"},
                clear=False,
            ):
                result = WorkspaceVerifier(cloud_root=root).verify(
                    self._authorized_request(workspace, (command,))
                )

            self.assertTrue(result.accepted)
            self.assertIn("<missing>", result.checks[0].summary)
            self.assertNotIn("host-secret-must-not-escape", result.checks[0].summary)

    def test_passes_explicit_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self._repository(root)
            (workspace / "README.md").write_text("changed\n", encoding="utf-8")
            command = self._python_command(
                "explicit-environment",
                "import os; print(os.environ['KORA_EXPLICIT_VALUE'])",
            )

            result = WorkspaceVerifier(
                cloud_root=root,
                environment={"KORA_EXPLICIT_VALUE": "passed-explicitly"},
            ).verify(self._authorized_request(workspace, (command,)))

            self.assertTrue(result.accepted)
            self.assertIn("passed-explicitly", result.checks[0].summary)

    def test_does_not_interpret_argv_through_a_shell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self._repository(root)
            (workspace / "README.md").write_text("changed\n", encoding="utf-8")
            marker = workspace / "shell-interpreted"
            payload = f"$(touch {marker})"
            command = VerificationCommand(
                name="literal-argv",
                argv=(
                    sys.executable,
                    "-c",
                    "import sys; print(sys.argv[1])",
                    payload,
                ),
            )

            result = WorkspaceVerifier(cloud_root=root).verify(
                self._authorized_request(workspace, (command,))
            )

            self.assertTrue(result.accepted)
            self.assertIn(payload, result.checks[0].summary)
            self.assertFalse(marker.exists())

    def test_sanitizes_and_bounds_command_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self._repository(root)
            (workspace / "README.md").write_text("changed\n", encoding="utf-8")
            command = self._python_command(
                "loud",
                "print('\\x1b[31m' + 'x' * 20000 + '\\x1b[0m')",
            )

            result = WorkspaceVerifier(cloud_root=root).verify(
                self._authorized_request(workspace, (command,))
            )

            summary = result.checks[0].summary
            self.assertTrue(result.accepted)
            self.assertLessEqual(len(summary), 4000)
            self.assertNotIn("\x1b", summary)
            self.assertIn("[truncated]", summary)

    def test_fingerprint_is_sha256_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self._repository(root)
            (workspace / "README.md").write_text("changed\n", encoding="utf-8")
            verifier = WorkspaceVerifier(cloud_root=root)
            request = WorkspaceVerificationRequest(workspace, ())

            first = verifier.verify(request)
            second = verifier.verify(request)
            environment = verifier._build_environment()
            status = subprocess.run(
                ["git", "status", "--porcelain=v1"],
                cwd=workspace,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            diff = subprocess.run(
                ["git", "diff", "--no-ext-diff", "--binary", "HEAD", "--"],
                cwd=workspace,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            expected = hashlib.sha256((status + "\n" + diff).encode("utf-8")).hexdigest()

            self.assertEqual(first.change_fingerprint, expected)
            self.assertEqual(first.change_fingerprint, second.change_fingerprint)
            self.assertEqual(first.artifacts[0].locator, second.artifacts[0].locator)

    def test_validates_command_contract(self) -> None:
        with self.assertRaises(WorkspaceVerificationError):
            VerificationCommand("", ("true",))
        with self.assertRaises(WorkspaceVerificationError):
            VerificationCommand("empty", ())
        with self.assertRaises(WorkspaceVerificationError):
            VerificationCommand("bad-item", ("true", 1))  # type: ignore[tuple-item]
        with self.assertRaises(WorkspaceVerificationError):
            VerificationCommand("bad-timeout", ("true",), 0)


if __name__ == "__main__":
    unittest.main()
