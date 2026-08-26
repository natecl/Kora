# Pinned Hermes runtime image

This image builds the exact Hermes revision recorded in
[`KORA_RUNTIME_LOCK.json`](../../KORA_RUNTIME_LOCK.json). It exists beneath
Kora's control plane and must never become a user-facing model or tool surface.

Build and verify:

```bash
docker build -t kora-hermes:68518c1f -f infra/hermes/Dockerfile .
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=256m kora-hermes:68518c1f acp --check
```

Real Kora work should mount only a disposable cloud workspace and inject
short-lived provider credentials. The user's Mac and long-lived connector
secrets must never be mounted into this container.
