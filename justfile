# Pull main, then test, migrate and deploy the Worker.
deploy:
    pixi run deploy

# Pull main, test, then deploy the server to FastAPI Cloud.
deploy-cloud:
    pixi run deploy-cloud

# Set up FastAPI Cloud with Neon and deploy, start to finish. Every sign-in
# happens in the browser: Neon (to look up the database's pooled connection
# string of the "pulseboard" project, creating it if needed), Cloudflare (only
# if you copy the D1 data across) and FastAPI Cloud. The string is stored on
# the app as the DATABASE_URL secret. Safe to run again. NEON_PROJECT (a name)
# or NEON_PROJECT_ID uses another Neon project.
cloud:
    #!/usr/bin/env bash
    set -euo pipefail
    neon() { npx --yes neonctl@8 --no-analytics "$@"; }
    git pull --ff-only
    pixi run test-worker

    neon me >/dev/null 2>&1 || neon login
    # The Neon project named pulseboard (NEON_PROJECT to use another name,
    # NEON_PROJECT_ID to name one by id), created if it doesn't exist yet.
    name="${NEON_PROJECT:-pulseboard}"
    project="${NEON_PROJECT_ID:-}"
    if [[ -z "$project" ]]; then
      project=$(neon projects list -o json | NAME="$name" pixi run -q python -c '
    import json, os, sys
    d = json.load(sys.stdin)
    ids = [p["id"] for p in (d.get("projects", []) if isinstance(d, dict) else d)
           if p.get("name") == os.environ["NAME"]]
    print(ids[0] if ids else "")')
      if [[ -z "$project" ]]; then
        echo "Creating the Neon project $name."
        project=$(neon projects create --name "$name" -o json | pixi run -q python -c '
    import json, sys; d = json.load(sys.stdin); print((d.get("project") or d)["id"])')
      fi
    fi
    url=$(neon connection-string --project-id "$project" --pooled)
    [[ "$url" == postgres* ]] || { echo "Neon did not return a connection string: $url" >&2; exit 1; }
    echo "Using Neon project $project (pooled endpoint)."

    read -rp "Copy feeds, subscriptions, articles and read state from Cloudflare D1 now? [y/N] " copy
    if [[ "$copy" =~ ^[Yy] ]]; then
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
