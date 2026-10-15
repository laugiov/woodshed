# woodshed in a container: nothing to install on the computer but Docker.
#
#   docker compose up -d          then open http://localhost:8000
#
# The container analyses the songs and serves the practice pages; the browser plays the audio, so
# the container needs no sound card. The library (songs, pages, lyrics) is a folder of the host; the
# models are downloaded at the first analysis into the cache volume, never baked into the image.

ARG PYTHON=python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641

FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv

FROM ${PYTHON} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/woodshed
WORKDIR /src
# sphn (read by Demucs) has no ARM Linux wheel: on ARM it is compiled, with Rust. This stage only.
# Its Opus library is built with CMake 4, which needs telling that Opus's old CMakeLists still builds.
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo PATH=/opt/cargo/bin:$PATH CMAKE_POLICY_VERSION_MINIMUM=3.5
RUN if [ "$(dpkg --print-architecture)" = arm64 ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends gcc g++ make cmake libc6-dev curl ca-certificates \
        && rm -rf /var/lib/apt/lists/* \
        && curl --proto '=https' --tlsv1.2 -sSf -o /tmp/rustup-init \
           https://static.rust-lang.org/rustup/archive/1.28.2/aarch64-unknown-linux-gnu/rustup-init \
        && echo "e3853c5a252fca15252d07cb23a1bdd9377a8c6f3efa01531109281ae47f841c  /tmp/rustup-init" | sha256sum -c - \
        && chmod +x /tmp/rustup-init \
        && /tmp/rustup-init -y --profile minimal --default-toolchain 1.90.0 --no-modify-path \
        && rm /tmp/rustup-init; \
    fi
# The locked dependencies first (CPU PyTorch, Demucs, beat_this): a code change does not reinstall them.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --extra stems --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra stems --no-editable

FROM ${PYTHON}
LABEL org.opencontainers.image.title="woodshed" \
      org.opencontainers.image.description="Turn any recording into a practice room for your band" \
      org.opencontainers.image.source="https://github.com/laugiov/woodshed" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 woodshed \
    && mkdir -p /library /cache \
    && chown woodshed:woodshed /library /cache \
    && chmod 1777 /cache
COPY --from=build /opt/woodshed /opt/woodshed
ENV PATH=/opt/woodshed/bin:$PATH \
    WOODSHED_CACHE=/cache \
    WOODSHED_CONTAINER=1 \
    NUMBA_CACHE_DIR=/cache/numba \
    PYTHONUNBUFFERED=1 \
    HF_HUB_VERBOSITY=error
USER woodshed
VOLUME ["/library", "/cache"]
EXPOSE 8000
# "healthy" once the library answers: `docker compose ps` and `up --wait` then say when it is ready.
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=6 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/', timeout=2)"]
ENTRYPOINT ["woodshed"]
# Inside the container every visitor comes through Docker's network, never from loopback: the app
# must accept them, and their uploads. Who can reach it is decided by the published port (compose.yaml).
CMD ["app", "/library", "--host", "0.0.0.0", "--allow-network", "--uploads-from-network", "--no-open", "--port", "8000"]
