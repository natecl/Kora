from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from kora.runtime import (
    Capability,
    ExecutionFenceTicket,
    RuntimeContractError,
    RuntimeJob,
)


UTC = timezone.utc


def _job(workspace: Path, **overrides: object) -> RuntimeJob:
    values: dict[str, object] = {
        "mission_id": "mission-1",
        "task_id": "task-1",
        "objective": "Run the approved task.",
        "instructions": "Produce only the requested result.",
        "workspace": workspace,
    }
    values.update(overrides)
    return RuntimeJob(**values)


class RuntimeContractTests(unittest.TestCase):
    def test_read_only_jobs_keep_compatibility_without_a_fence(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        job = _job(Path("/tmp/kora-runtime"), capabilities=frozenset({Capability.NETWORK_READ}))
        self.assertFalse(job.requires_execution_fence)
        self.assertIsNone(job.validate_execution_fence(at=now))

    def test_effect_bearing_jobs_require_a_kora_fence(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        job = _job(
            Path("/tmp/kora-runtime"),
            capabilities=frozenset({Capability.WORKSPACE_WRITE}),
        )
        self.assertTrue(job.requires_execution_fence)
        with self.assertRaises(RuntimeContractError):
            job.validate_execution_fence(at=now)

        ticket = ExecutionFenceTicket(
            attempt_id="attempt-1",
            lease_owner="worker-1",
            fencing_token=4,
            lease_expires_at=now + timedelta(seconds=10),
            cancellation_identity="cancel-1",
        )
        fenced_job = _job(
            Path("/tmp/kora-runtime"),
            capabilities=frozenset({Capability.WORKSPACE_WRITE}),
            execution_fence=ticket,
        )
        self.assertIs(
            fenced_job.validate_execution_fence(
                at=now + timedelta(seconds=1),
                cancellation_identity="cancel-1",
            ),
            ticket,
        )
        self.assertIs(fenced_job.fence_ticket, ticket)

    def test_fence_ticket_validates_identity_and_expiry(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        attempt = SimpleNamespace(
            attempt_id="attempt-2",
            lease_owner="worker-2",
            fencing_token=8,
            lease_expires_at=now + timedelta(seconds=5),
        )
        ticket = ExecutionFenceTicket.from_attempt(
            attempt,
            cancellation_identity="cancel-2",
            at=now,
        )
        self.assertTrue(ticket.is_active(now + timedelta(seconds=4)))
        with self.assertRaises(RuntimeContractError):
            ticket.validate(attempt_id="other-attempt", at=now)
        with self.assertRaises(RuntimeContractError):
            ticket.validate(cancellation_identity="cancel-other", at=now)
        with self.assertRaises(RuntimeContractError):
            ticket.validate(at=now + timedelta(seconds=5))


if __name__ == "__main__":
    unittest.main()
