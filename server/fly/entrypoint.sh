#!/bin/sh
# The machine's whole life: serve the component with `wasmtime serve`, apply
# migrations once it is up, then refresh due feeds every
# REFRESH_EVERY_MINUTES (default 30; 0 for never) through an internal route
# guarded by a secret made up here at boot.
set -eu
component=${PULSEBOARD_COMPONENT:-/app/pulseboard-server.wasm}
dist=${PULSEBOARD_DIST:-/app/dist}
port=${PORT:-8080}
CRON_SECRET=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')
export CRON_SECRET

set -- serve -S cli=y --addr "0.0.0.0:$port" --dir "$dist::/dist" --env CRON_SECRET
for name in DATABASE_URL NEON_SQL_URL PUBLIC_ORIGIN PULSEBOARD_TEST_UPSTREAM; do
  if [ -n "$(printenv "$name" || true)" ]; then set -- "$@" --env "$name"; fi
done
wasmtime "$@" "$component" &
server=$!
trap 'kill $server 2>/dev/null' INT TERM

base="http://127.0.0.1:$port"
until curl -fsS "$base/health" >/dev/null 2>&1; do
  kill -0 $server 2>/dev/null || { echo "pulseboard: the server exited" >&2; exit 1; }
  sleep 1
done
curl -fsS -X POST -H "x-pulseboard-cron: $CRON_SECRET" "$base/internal/migrate" && echo

minutes=${REFRESH_EVERY_MINUTES:-30}
if [ "$minutes" -gt 0 ]; then
  (
    while sleep $((minutes * 60)); do
      curl -fsS -m 600 -X POST -H "x-pulseboard-cron: $CRON_SECRET" "$base/internal/cron" >/dev/null \
        || echo "pulseboard: scheduled refresh failed" >&2
    done
  ) &
fi
wait $server
