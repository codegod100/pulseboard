# Pull main, then test, migrate and deploy the Worker.
deploy:
    pixi run deploy

# Pull main, test, then deploy the server to FastAPI Cloud.
deploy-cloud:
    pixi run deploy-cloud

# Set up FastAPI Cloud with Neon and deploy, start to finish. Every sign-in
# happens in the browser: Neon (to look up the database's pooled connection
# string, creating a "pulseboard" project if you have none), Cloudflare (only
# if you copy the D1 data across) and FastAPI Cloud. The string is stored on
# the app as the DATABASE_URL secret. Safe to run again. NEON_PROJECT_ID picks
# the project without asking.
cloud:
    #!/usr/bin/env bash
    set -euo pipefail
    neon() { npx --yes neonctl@8 --no-analytics "$@"; }
    tab=$'\t'
    git pull --ff-only
    pixi run test-worker

    neon me >/dev/null 2>&1 || neon login
    project="${NEON_PROJECT_ID:-}"
    if [[ -z "$project" ]]; then
      rows=()
      while IFS= read -r line; do rows+=("$line"); done < <(neon projects list -o json | pixi run -q python -c '
    import json, sys
    d = json.load(sys.stdin)
    for p in (d.get("projects", []) if isinstance(d, dict) else d):
        print(p["id"] + "\t" + p.get("name", ""))')
      if (( ${#rows[@]} == 0 )); then
        echo "No Neon projects yet; creating one called pulseboard."
        project=$(neon projects create --name pulseboard -o json | pixi run -q python -c '
    import json, sys; d = json.load(sys.stdin); print((d.get("project") or d)["id"])')
      elif (( ${#rows[@]} == 1 )); then
        project="${rows[0]%%${tab}*}"
      else
        echo "Which Neon project holds Pulseboard's database?"
        for i in "${!rows[@]}"; do printf '  %d) %s\n' $((i + 1)) "${rows[$i]#*${tab}} (${rows[$i]%%${tab}*})"; done
        read -rp "Number: " n
        project="${rows[$((n - 1))]%%${tab}*}"
      fi
    fi
    url=$(neon connection-string --project-id "$project" --pooled)
    [[ "$url" == postgres* ]] || { echo "Neon did not return a connection string: $url" >&2; exit 1; }
    echo "Using Neon project $project (pooled endpoint)."

    read -rp "Copy feeds, subscriptions, articles and read state from Cloudflare D1 now? [y/N] " copy
    if [[ "$copy" =~ ^[Yy] ]]; then
      npx --yes wrangler@4 whoami >/dev/null 2>&1 || npx --yes wrangler@4 login
      DATABASE_URL="$url" pixi run migrate-d1
    fi
    # The first deploy signs in to FastAPI Cloud and creates (or links) the app;
    # the second picks up DATABASE_URL.
    uv run --frozen fastapi deploy
    uv run --frozen fastapi cloud env set --secret DATABASE_URL "$url"
    uv run --frozen fastapi deploy

# Copy the existing data from Cloudflare D1 into Neon (DATABASE_URL). Safe to run again.
migrate-d1:
    pixi run migrate-d1
