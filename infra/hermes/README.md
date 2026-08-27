# Bootstrap Hermes runtime image

This image builds the exact Hermes revision, Python base-image digest, and uv
version recorded in [`KORA_RUNTIME_LOCK.json`](../../KORA_RUNTIME_LOCK.json).
It exists beneath Kora's control plane and must never become a user-facing
model or tool surface.

This is the exact-commit/container lock for the bootstrap spike, not the final
runtime-hardening pin. The planned target is a tagged Hermes release plus an
immutable container image digest, validated through the Kora vertical-slice
gates. OpenHands remains only a gated fallback if Hermes fails those gates.

Build and verify:

```bash
docker build -t kora-hermes:68518c1f -f infra/hermes/Dockerfile .
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=256m kora-hermes:68518c1f acp --check
```

`HERMES_HOME` points into the ephemeral `/tmp` filesystem, so Hermes can
initialize its runtime state without writing to the read-only image. Real Kora
work should mount only a disposable cloud workspace and inject short-lived
provider credentials. The user's Mac and long-lived connector secrets must
never be mounted into this container.
