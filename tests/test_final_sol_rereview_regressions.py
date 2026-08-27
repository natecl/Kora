"""Independent second-pass coverage for the remaining Sol P1 boundaries."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import kora.verification.verifier as verifier_module
from kora.runtime import (
    Capability,
    ExecutionFenceTicket,
    HermesRuntimeAdapter,
    HermesRuntimeError,
    IsolationMode,
    RuntimeJob,
    RuntimeStatus,
)
from kora.verification import (
    VerificationCommand,
    WorkspaceVerificationError,
    WorkspaceVerificationRequest,
    WorkspaceVerifier,
)


def _git(workspace: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )


def _git_repository(path: Path, *, ignored_name: str | None = None) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    if ignored_name is not None:
        (path / ".gitignore").write_text(f"{ignored_name}\n", encoding="utf-8")
    _git(path, "add", "--all")
    _git(
        path,
        "-c",
        "user.name=Kora Test",
        "-c",
        "user.email=kora@example.test",
        "commit",
        "-qm",
        "base",
    )
    return path


def _python_command(name: str, code: str) -> VerificationCommand:
    return VerificationCommand(name=name, argv=(sys.executable, "-c", code))


def _write_launch_executable(path: Path) -> None:
    path.write_text(
        """#!/bin/sh
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--usage-file" ]; then
    usage_path="$2"
    shift 2
  else
    shift
  fi
done
printf 'effect\\n' > hermes-spawn-marker.txt
printf '{}\\n' > "$usage_path"
printf 'KORA_TASK_COMPLETE\\n'
""",
        encoding="utf-8",
    )
    path.chmod(0o700)


class _SwapWorkspaceAtExecutableResolution(HermesRuntimeAdapter):
    """Use the real adapter while injecting a pathname replacement at setup."""

    def __init__(
        self,
        *,
        swap_path: Path,
        renamed_path: Path,
        redirected_path: Path,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.swap_path = swap_path
        self.renamed_path = renamed_path
        self.redirected_path = redirected_path
        self.swapped = False

    def _resolve_executable(self) -> str:
        if not self.swapped:
            self.swap_path.rename(self.renamed_path)
            self.swap_path.symlink_to(self.redirected_path, target_is_directory=True)
            self.swapped = True
        return super()._resolve_executable()


class _SwapWorkspaceBeforeVerifierCommand(WorkspaceVerifier):
    """Use the real verifier while replacing its cwd just before one command."""

    def __init__(
        self,
        *,
        trigger: tuple[str, ...],
        swap_path: Path,
        renamed_path: Path,
        redirected_path: Path,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.trigger = trigger
        self.swap_path = swap_path
        self.renamed_path = renamed_path
        self.redirected_path = redirected_path
        self.swapped = False

    def _run_process(self, argv: tuple[str, ...], **kwargs: object):
        if not self.swapped and tuple(argv) == self.trigger:
            self.swap_path.rename(self.renamed_path)
            self.swap_path.symlink_to(self.redirected_path, target_is_directory=True)
            self.swapped = True
        return super()._run_process(argv, **kwargs)


class FinalSolRereviewRegressionTests(unittest.TestCase):
    @staticmethod
    def _fence_ticket(label: str) -> ExecutionFenceTicket:
        return ExecutionFenceTicket(
            attempt_id=f"attempt-{label}",
            lease_owner="rereview-test",
            fencing_token=1,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            cancellation_identity=f"cancel-{label}",
        )

    @staticmethod
    def _effect_job(
        workspace: Path,
        ticket: ExecutionFenceTicket,
        *,
        live_fence_validator: object | None = None,
    ) -> RuntimeJob:
        return RuntimeJob(
            mission_id="mission-rereview",
            task_id="task-rereview",
            objective="Run the approved directory binding check.",
            instructions="Run only the approved check.",
            workspace=workspace,
            capabilities=frozenset({Capability.WORKSPACE_WRITE}),
            isolation=IsolationMode.CLOUD_SANDBOX,
            execution_fence=ticket,
            live_fence_validator=live_fence_validator,
        )

    def test_direct_verifier_commands_are_fail_closed_without_explicit_execute_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="kora-rereview-authority-") as directory:
            root = Path(directory)
            workspace = _git_repository(root / "workspace")
            verifier = WorkspaceVerifier(cloud_root=root)

            with self.subTest(case="commandless-default-inspection-positive"):
                inspection = verifier.verify(
                    WorkspaceVerificationRequest(
                        workspace=workspace,
                        commands=(),
                        require_changes=False,
                    )
                )
                self.assertTrue(inspection.accepted)

            cases = (
                ("defaults", {}),
                (
                    "missing-execute-capability",
                    {
                        "execution_authorized": True,
                        "execution_granted": True,
                        "require_execution_authority": True,
                        "live_fence_validator": lambda: True,
                    },
                ),
                (
                    "missing-execute-grant",
                    {
                        "execution_authorized": True,
                        "execution_capability": True,
                        "require_execution_authority": True,
                        "live_fence_validator": lambda: True,
                    },
                ),
                (
                    "missing-live-fence",
                    {
                        "execution_authorized": True,
                        "execution_capability": True,
                        "execution_granted": True,
                        "require_execution_authority": True,
                    },
                ),
            )
            for case, authority in cases:
                marker = root / f"{case}-outside-workspace-write.txt"
                command = _python_command(
                    f"{case} outside-workspace write",
                    (
                        "from pathlib import Path; "
                        f"Path({str(marker)!r}).write_text('must-not-run\\n', encoding='utf-8')"
                    ),
                )
                with self.subTest(case=case):
                    request_values: dict[str, object] = {
                        "workspace": workspace,
                        "commands": (command,),
                        "require_changes": False,
                    }
                    request_values.update(authority)
                    try:
                        result = verifier.verify(WorkspaceVerificationRequest(**request_values))
                    except WorkspaceVerificationError as exc:
                        self.assertIn("authority", str(exc).lower())
                    else:
                        self.assertFalse(result.accepted)
                        self.assertEqual(result.checks, ())
                    self.assertFalse(marker.exists())

            with self.subTest(case="all-explicit-authority-live-fence-positive"):
                fence_calls: list[str] = []

                def live_fence() -> bool:
                    fence_calls.append("validated")
                    return True

                result = verifier.verify(
                    WorkspaceVerificationRequest(
                        workspace=workspace,
                        commands=(_python_command("authorized check", "print('ok')"),),
                        require_changes=False,
                        execution_authorized=True,
                        execution_capability=True,
                        execution_granted=True,
                        require_execution_authority=True,
                        live_fence_validator=live_fence,
                    )
                )
                self.assertTrue(result.accepted)
                self.assertEqual([check.name for check in result.checks], ["authorized check"])
                self.assertTrue(result.checks[0].passed)
                self.assertGreater(len(fence_calls), 0)

    def test_spawn_directory_replacement_cannot_redirect_real_adapters(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kora-rereview-spawn-") as directory:
            root = Path(directory)
            executable = root / "fake-hermes"
            _write_launch_executable(executable)

            workspace = root / "authorized-workspace"
            workspace.mkdir()
            renamed_workspace = root / "authorized-workspace-renamed"
            redirected_workspace = root / "redirected-workspace"
            redirected_workspace.mkdir()
            authorized_stat = os.stat(workspace)
            authorized_identity = (authorized_stat.st_dev, authorized_stat.st_ino)
            ticket = self._fence_ticket("hermes")

            def live_fence(candidate: ExecutionFenceTicket) -> bool:
                return candidate is ticket

            adapter = _SwapWorkspaceAtExecutableResolution(
                cloud_root=root,
                hermes_executable=executable,
                swap_path=workspace,
                renamed_path=renamed_workspace,
                redirected_path=redirected_workspace,
            )
            runtime_result = None
            runtime_error: BaseException | None = None
            with self.subTest(case="hermes-directory-replacement"):
                try:
                    runtime_result = adapter.run(
                        self._effect_job(
                            workspace,
                            ticket,
                            live_fence_validator=live_fence,
                        )
                    )
                except (HermesRuntimeError, OSError, subprocess.SubprocessError) as exc:
                    runtime_error = exc

                self.assertTrue(adapter.swapped)
                self.assertTrue(workspace.is_symlink())
                renamed_stat = os.stat(renamed_workspace)
                self.assertEqual(
                    (renamed_stat.st_dev, renamed_stat.st_ino),
                    authorized_identity,
                )
                self.assertFalse(
                    (redirected_workspace / "hermes-spawn-marker.txt").exists()
                )
                safe_failure = runtime_error is not None or (
                    runtime_result is not None
                    and runtime_result.status is not RuntimeStatus.COMPLETED
                )
                self.assertTrue(
                    (renamed_workspace / "hermes-spawn-marker.txt").exists()
                    or safe_failure,
                    "the launch must stay on the authorized inode or fail closed",
                )

            with self.subTest(case="canonical-hermes-directory-positive"):
                positive_workspace = root / "positive-workspace"
                positive_workspace.mkdir()
                positive_ticket = self._fence_ticket("hermes-positive")
                positive_result = HermesRuntimeAdapter(
                    cloud_root=root,
                    hermes_executable=executable,
                ).run(self._effect_job(positive_workspace, positive_ticket))
                self.assertEqual(positive_result.status, RuntimeStatus.COMPLETED)
                self.assertTrue(
                    (positive_workspace / "hermes-spawn-marker.txt").exists()
                )

            verifier_workspace = _git_repository(root / "verifier-workspace")
            verifier_renamed = root / "verifier-workspace-renamed"
            verifier_redirected = root / "verifier-redirected-workspace"
            verifier_redirected.mkdir()
            verifier_identity_stat = os.stat(verifier_workspace)
            verifier_identity = (
                verifier_identity_stat.st_dev,
                verifier_identity_stat.st_ino,
            )
            verifier_command = _python_command(
                "verifier spawn check",
                "from pathlib import Path; Path('verifier-spawn-marker.txt').write_text('effect\\n')",
            )
            swapping_verifier = _SwapWorkspaceBeforeVerifierCommand(
                cloud_root=root,
                trigger=verifier_command.argv,
                swap_path=verifier_workspace,
                renamed_path=verifier_renamed,
                redirected_path=verifier_redirected,
            )
            with self.subTest(case="verifier-directory-replacement"):
                verifier_result = swapping_verifier.verify(
                    WorkspaceVerificationRequest(
                        workspace=verifier_workspace,
                        commands=(verifier_command,),
                        require_changes=False,
                        execution_authorized=True,
                        execution_capability=True,
                        execution_granted=True,
                        require_execution_authority=True,
                        live_fence_validator=lambda: True,
                    )
                )
                self.assertTrue(swapping_verifier.swapped)
                renamed_verifier_stat = os.stat(verifier_renamed)
                self.assertEqual(
                    (renamed_verifier_stat.st_dev, renamed_verifier_stat.st_ino),
                    verifier_identity,
                )
                self.assertFalse(
                    (verifier_redirected / "verifier-spawn-marker.txt").exists()
                )
                if not (verifier_renamed / "verifier-spawn-marker.txt").exists():
                    self.assertFalse(verifier_result.accepted)

            with self.subTest(case="verifier-device-inode-mismatch-rejected"):
                mismatch_workspace = _git_repository(root / "mismatch-workspace")
                candidate = mismatch_workspace / "candidate.bin"
                other = mismatch_workspace / "other.bin"
                candidate.write_bytes(b"same-size\n")
                other.write_bytes(b"same-size\n")
                candidate.chmod(0o600)
                other.chmod(0o600)
                candidate_stat = os.stat(candidate)
                wrong_stat = os.stat(other)
                candidate_identity = (candidate_stat.st_dev, candidate_stat.st_ino)
                real_fstat = os.fstat

                def fstat_with_mismatch(file_descriptor: int) -> os.stat_result:
                    observed = real_fstat(file_descriptor)
                    if (observed.st_dev, observed.st_ino) == candidate_identity:
                        return wrong_stat
                    return observed

                with patch(
                    "kora.verification.verifier.os.fstat",
                    side_effect=fstat_with_mismatch,
                ):
                    mismatch_result = WorkspaceVerifier(cloud_root=root).verify(
                        WorkspaceVerificationRequest(
                            workspace=mismatch_workspace,
                            commands=(),
                            require_changes=False,
                        )
                    )
                self.assertFalse(mismatch_result.accepted)
                self.assertIn("changed while", mismatch_result.summary)
                self.assertIsNone(mismatch_result.change_fingerprint)

    def test_gitignored_untracked_state_is_fingerprinted_and_mutation_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kora-rereview-ignored-") as directory:
            root = Path(directory)
            workspace = _git_repository(root / "workspace", ignored_name="ignored.dat")
            ignored = workspace / "ignored.dat"
            verifier = WorkspaceVerifier(cloud_root=root)

            def fingerprint() -> str:
                result = verifier.verify(
                    WorkspaceVerificationRequest(
                        workspace=workspace,
                        commands=(),
                        require_changes=False,
                    )
                )
                self.assertIsNotNone(result.change_fingerprint)
                return result.change_fingerprint or ""

            ignored.write_bytes(b"bytes-one\n")
            ignored.chmod(0o600)
            first = fingerprint()
            ignored.write_bytes(b"bytes-two\n")
            second = fingerprint()
            with self.subTest(component="ignored-bytes"):
                self.assertNotEqual(first, second)

            ignored.chmod(0o755)
            third = fingerprint()
            with self.subTest(component="ignored-mode"):
                self.assertNotEqual(second, third)

            outside_target = root / "ignored-symlink-target.txt"
            outside_target.write_text("target\n", encoding="utf-8")
            ignored.unlink()
            ignored.symlink_to(outside_target)
            fourth = fingerprint()
            with self.subTest(component="ignored-type"):
                self.assertNotEqual(third, fourth)

            ignored.unlink()
            ignored.write_text("before\n", encoding="utf-8")
            ignored.chmod(0o600)
            mutate = _python_command(
                "authorized ignored mutation",
                "from pathlib import Path; Path('ignored.dat').write_text('after\\n', encoding='utf-8')",
            )
            with self.subTest(case="authorized-ignored-mutation-rejected"):
                mutation_result = verifier.verify(
                    WorkspaceVerificationRequest(
                        workspace=workspace,
                        commands=(mutate,),
                        require_changes=False,
                        execution_authorized=True,
                        execution_capability=True,
                        execution_granted=True,
                        require_execution_authority=True,
                        live_fence_validator=lambda: True,
                    )
                )
                self.assertFalse(mutation_result.accepted)
                self.assertIn("mutated the workspace", mutation_result.summary)
                self.assertEqual([check.name for check in mutation_result.checks], [mutate.name])
                self.assertTrue(mutation_result.checks[0].passed)

            with self.subTest(case="authorized-unchanged-ignored-check-positive"):
                unchanged = _python_command(
                    "authorized ignored check",
                    "from pathlib import Path; assert Path('ignored.dat').read_text(encoding='utf-8') == 'after\\n'",
                )
                unchanged_result = verifier.verify(
                    WorkspaceVerificationRequest(
                        workspace=workspace,
                        commands=(unchanged,),
                        require_changes=False,
                        execution_authorized=True,
                        execution_capability=True,
                        execution_granted=True,
                        require_execution_authority=True,
                        live_fence_validator=lambda: True,
                    )
                )
                self.assertTrue(unchanged_result.accepted)
                self.assertTrue(unchanged_result.checks[0].passed)

    def test_ignored_empty_descendant_directory_is_fingerprinted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kora-rereview-ignored-tree-") as directory:
            root = Path(directory)
            workspace = _git_repository(root / "workspace", ignored_name="ignored/")
            ignored = workspace / "ignored"
            ignored.mkdir()
            (ignored / "keep").write_text("keep\n", encoding="utf-8")
            verifier = WorkspaceVerifier(cloud_root=root)

            def request(
                commands: tuple[VerificationCommand, ...],
            ) -> WorkspaceVerificationRequest:
                return WorkspaceVerificationRequest(
                    workspace=workspace,
                    commands=commands,
                    require_changes=False,
                    execution_authorized=True,
                    execution_capability=True,
                    execution_granted=True,
                    require_execution_authority=True,
                    live_fence_validator=lambda: True,
                )

            before = verifier.verify(request(()))
            self.assertTrue(before.accepted)
            self.assertIsNotNone(before.change_fingerprint)

            unchanged = _python_command(
                "authorized unchanged ignored tree check",
                "from pathlib import Path; "
                "assert Path('ignored/keep').read_text(encoding='utf-8') == 'keep\\n'",
            )
            unchanged_result = verifier.verify(request((unchanged,)))
            with self.subTest(case="unchanged-tree-control"):
                self.assertTrue(unchanged_result.accepted)
                self.assertEqual(
                    unchanged_result.change_fingerprint,
                    before.change_fingerprint,
                )

            create_empty = _python_command(
                "authorized ignored empty directory mutation",
                "from pathlib import Path; Path('ignored/created-empty').mkdir()",
            )
            mutation_result = verifier.verify(request((create_empty,)))
            with self.subTest(case="empty-descendant-mutation-rejected"):
                self.assertFalse(mutation_result.accepted)
                self.assertIn("mutated the workspace", mutation_result.summary)
                self.assertTrue(mutation_result.checks[0].passed)
                self.assertNotEqual(
                    mutation_result.change_fingerprint,
                    before.change_fingerprint,
                )

            after = _python_command(
                "authorized created empty directory check",
                "from pathlib import Path; assert Path('ignored/created-empty').is_dir()",
            )
            after_result = verifier.verify(request((after,)))
            with self.subTest(case="unchanged-created-empty-tree-control"):
                self.assertTrue(after_result.accepted)
                self.assertEqual(
                    after_result.change_fingerprint,
                    mutation_result.change_fingerprint,
                )

    def test_authorized_command_cannot_hide_nested_git_mutation_under_ignored_tree(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="kora-rereview-nested-git-") as directory:
            root = Path(directory)
            workspace = _git_repository(root / "workspace", ignored_name="ignored/")
            ignored = workspace / "ignored"
            ignored.mkdir()
            (ignored / "keep").write_text("keep\n", encoding="utf-8")
            verifier = WorkspaceVerifier(cloud_root=root)

            def request(
                commands: tuple[VerificationCommand, ...],
            ) -> WorkspaceVerificationRequest:
                return WorkspaceVerificationRequest(
                    workspace=workspace,
                    commands=commands,
                    require_changes=False,
                    execution_authorized=True,
                    execution_capability=True,
                    execution_granted=True,
                    require_execution_authority=True,
                    live_fence_validator=lambda: True,
                )

            before = verifier.verify(request(()))
            self.assertTrue(before.accepted)
            self.assertIsNotNone(before.change_fingerprint)

            unchanged = _python_command(
                "authorized unchanged ignored tree control",
                "from pathlib import Path; "
                "assert Path('ignored/keep').read_text(encoding='utf-8') == 'keep\\n'",
            )
            unchanged_result = verifier.verify(request((unchanged,)))
            with self.subTest(case="unchanged-tree-control"):
                self.assertTrue(unchanged_result.accepted)
                self.assertEqual(
                    unchanged_result.change_fingerprint,
                    before.change_fingerprint,
                )

            create_nested_git = _python_command(
                "authorized nested git mutation",
                "from pathlib import Path; Path('ignored/.git').mkdir()",
            )
            mutation_result = verifier.verify(request((create_nested_git,)))
            with self.subTest(case="nested-git-mutation-rejected"):
                self.assertFalse(mutation_result.accepted)
                self.assertTrue((ignored / ".git").is_dir())
                self.assertTrue(mutation_result.checks[0].passed)
                self.assertIsNotNone(mutation_result.change_fingerprint)
                self.assertNotEqual(
                    mutation_result.change_fingerprint,
                    before.change_fingerprint,
                )

    def test_tracked_sibling_does_not_consume_untracked_byte_budget(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kora-rereview-tracked-sibling-") as directory:
            root = Path(directory)
            workspace = _git_repository(root / "workspace")
            sibling_directory = workspace / "siblings"
            sibling_directory.mkdir()
            tracked = sibling_directory / "tracked.bin"
            tracked.touch()
            os.truncate(tracked, verifier_module._UNTRACKED_BYTE_LIMIT + 1)
            self.assertGreater(
                tracked.stat().st_size,
                verifier_module._UNTRACKED_BYTE_LIMIT,
            )
            _git(workspace, "add", "siblings/tracked.bin")
            _git(
                workspace,
                "-c",
                "user.name=Kora Test",
                "-c",
                "user.email=kora@example.test",
                "commit",
                "-qm",
                "large tracked sibling",
            )
            untracked = sibling_directory / "untracked.txt"
            untracked.write_text("tiny\n", encoding="utf-8")

            result = WorkspaceVerifier(cloud_root=root).verify(
                WorkspaceVerificationRequest(
                    workspace=workspace,
                    commands=(),
                    require_changes=True,
                )
            )
            self.assertTrue(result.accepted)
            self.assertIsNotNone(result.change_fingerprint)
            self.assertTrue(untracked.exists())

    def test_nested_git_entry_under_tracked_parent_cannot_bypass_snapshot(self) -> None:
        for entry_kind in ("directory", "file"):
            with self.subTest(entry_kind=entry_kind):
                with tempfile.TemporaryDirectory(
                    prefix=f"kora-rereview-tracked-parent-{entry_kind}-"
                ) as directory:
                    root = Path(directory)
                    workspace = _git_repository(root / "workspace")
                    source = workspace / "src"
                    source.mkdir()
                    (source / "tracked").write_text("tracked\n", encoding="utf-8")
                    _git(workspace, "add", "src/tracked")
                    _git(
                        workspace,
                        "-c",
                        "user.name=Kora Test",
                        "-c",
                        "user.email=kora@example.test",
                        "commit",
                        "-qm",
                        "tracked source fixture",
                    )
                    (source / "u").write_text("u\n", encoding="utf-8")
                    verifier = WorkspaceVerifier(cloud_root=root)

                    def request(
                        commands: tuple[VerificationCommand, ...],
                    ) -> WorkspaceVerificationRequest:
                        return WorkspaceVerificationRequest(
                            workspace=workspace,
                            commands=commands,
                            require_changes=True,
                            execution_authorized=True,
                            execution_capability=True,
                            execution_granted=True,
                            require_execution_authority=True,
                            live_fence_validator=lambda: True,
                        )

                    before = verifier.verify(request(()))
                    self.assertTrue(before.accepted)
                    self.assertIsNotNone(before.change_fingerprint)

                    root_git_marker = workspace / ".git" / "kora-root-metadata-test"
                    root_git_marker.write_text("root metadata\n", encoding="utf-8")
                    root_git_result = verifier.verify(request(()))
                    with self.subTest(component="root-git-outside-content"):
                        self.assertTrue(root_git_result.accepted)
                        self.assertEqual(
                            root_git_result.change_fingerprint,
                            before.change_fingerprint,
                        )

                    unchanged = _python_command(
                        "authorized unchanged tracked-parent control",
                        "from pathlib import Path; "
                        "assert Path('src/tracked').read_text(encoding='utf-8') == 'tracked\\n'; "
                        "assert Path('src/u').read_text(encoding='utf-8') == 'u\\n'",
                    )
                    unchanged_result = verifier.verify(request((unchanged,)))
                    with self.subTest(component="unchanged-tree-control"):
                        self.assertTrue(unchanged_result.accepted)
                        self.assertEqual(
                            unchanged_result.change_fingerprint,
                            before.change_fingerprint,
                        )

                    nested = source / ".git"
                    if entry_kind == "directory":
                        create_nested = _python_command(
                            "authorized nested git directory mutation",
                            "from pathlib import Path; Path('src/.git').mkdir()",
                        )
                    else:
                        create_nested = _python_command(
                            "authorized nested git file mutation",
                            "from pathlib import Path; "
                            "Path('src/.git').write_text('nested git\\n', encoding='utf-8')",
                        )

                    mutation_result = verifier.verify(request((create_nested,)))
                    reported_paths = subprocess.run(
                        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                        cwd=workspace,
                        capture_output=True,
                        check=True,
                    ).stdout
                    with self.subTest(component="git-omits-nested-entry"):
                        self.assertNotIn(b"src/.git", reported_paths)
                    with self.subTest(component="nested-git-mutation-rejected"):
                        self.assertFalse(mutation_result.accepted)
                        if entry_kind == "directory":
                            self.assertTrue(nested.is_dir())
                        else:
                            self.assertTrue(nested.is_file())
                        self.assertTrue(mutation_result.checks[0].passed)
                        self.assertIsNotNone(mutation_result.change_fingerprint)
                        self.assertNotEqual(
                            mutation_result.change_fingerprint,
                            before.change_fingerprint,
                        )


if __name__ == "__main__":
    unittest.main()
