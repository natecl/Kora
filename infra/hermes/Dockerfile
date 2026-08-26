FROM python:3.13-slim

ARG HERMES_REPOSITORY=https://github.com/NousResearch/hermes-agent.git
ARG HERMES_COMMIT=68518c1f9bca11d9f5dbdf59ecf7e024cce057ba
ARG UV_VERSION=0.11.15

LABEL org.opencontainers.image.source="${HERMES_REPOSITORY}"
LABEL org.opencontainers.image.revision="${HERMES_COMMIT}"
LABEL org.opencontainers.image.licenses="MIT"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /opt/hermes
RUN git clone --filter=blob:none "${HERMES_REPOSITORY}" . \
    && git checkout --detach "${HERMES_COMMIT}" \
    && test "$(git rev-parse HEAD)" = "${HERMES_COMMIT}"

RUN uv sync --frozen --extra acp --no-dev

ENV PATH="/opt/hermes/.venv/bin:${PATH}"
ENV HERMES_ACP_SKIP_CONFIGURED_MCP=1

WORKDIR /workspace
ENTRYPOINT ["hermes"]
CMD ["acp", "--check"]
