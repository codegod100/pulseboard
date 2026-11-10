# The Qt server for Fly.io: build the component with qt2wasm, then run it with
# `wasmtime serve` next to the web client's files. Built from the repository
# root (fly.toml there points here).

FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://github.com/prefix-dev/pixi/releases/download/v0.84.1/pixi-x86_64-unknown-linux-musl.tar.gz \
    | tar -xz -C /usr/local/bin pixi
WORKDIR /src/server
COPY server/pixi.toml ./
RUN pixi install -e default
COPY server/ ./
RUN pixi run -e default build

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/server/.pixi/envs/default/bin/wasmtime /usr/local/bin/wasmtime
COPY --from=build /src/server/build/pulseboard-server.wasm /app/pulseboard-server.wasm
COPY web/dist /app/dist
COPY server/fly/entrypoint.sh /app/entrypoint.sh
ENV PORT=8080
EXPOSE 8080
CMD ["/app/entrypoint.sh"]
