#!/usr/bin/env bash
# Run the server tests. Uses PULSEBOARD_TEST_POSTGRES when set (CI's postgres
# service); otherwise starts a throwaway Postgres cluster for the run.
set -euo pipefail
cd "$(dirname "$0")"
if [[ -z "${PULSEBOARD_TEST_POSTGRES:-}" ]]; then
  data=$(mktemp -d)
  port=55432
  as=()
  if [[ $(id -u) == 0 ]]; then  # initdb refuses to run as root
    id pbtest >/dev/null 2>&1 || useradd -M pbtest
    chown pbtest "$data"
    as=(su pbtest -s /bin/bash -c)
  else
    as=(bash -c)
  fi
  "${as[@]}" "initdb -D '$data' -A trust -U postgres >/dev/null && pg_ctl -D '$data' -o '-p $port -k /tmp -c listen_addresses=127.0.0.1' -l '$data/log' -w start >/dev/null"
  trap '"${as[@]}" "pg_ctl -D '"'$data'"' -m immediate stop" >/dev/null; rm -rf "$data"' EXIT
  export PULSEBOARD_TEST_POSTGRES="postgresql://postgres@127.0.0.1:$port/postgres"
fi
python -m pytest -q "$@"
