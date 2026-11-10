# Signs in to Fly and Neon in the browser, creates the Fly app if it doesn't
# exist (FLY_APP names it, default pulseboard), stores the Neon connection
# string on it as the DATABASE_URL secret, and deploys. Fly builds the image
# remotely, so no Docker is needed. Safe to run again.
#
# Deploy the Qt server (server/) to Fly.io, start to finish
deploy:
    #!/usr/bin/env bash
    set -euo pipefail
    git pull --ff-only
    export PATH="$HOME/.fly/bin:$PATH"
    if ! type -P flyctl >/dev/null; then
      curl -fsSL https://fly.io/install.sh | sh
    fi
    fly() { flyctl "$@"; }
    fly auth whoami >/dev/null 2>&1 || fly auth login
    app="${FLY_APP:-pulseboard}"
    if ! fly status -a "$app" >/dev/null 2>&1; then
      echo "Creating the Fly app $app (set FLY_APP if the name is taken)."
      fly apps create "$app"
    fi
    url=$({{just_executable()}} neon-url)
    fly secrets set --stage -a "$app" DATABASE_URL="$url"
    fly deploy --remote-only -a "$app"
    echo "Deployed: https://$app.fly.dev"

# Redeploy the Qt server to Fly once `just deploy` has set it up.
redeploy:
    git pull --ff-only
    PATH="$HOME/.fly/bin:$PATH" flyctl deploy --remote-only -a "${FLY_APP:-pulseboard}"

# Optionally copies the Cloudflare D1 data across first.
#
# The previous setup: the Python server (worker/) on FastAPI Cloud with Neon
deploy-fastapi:
    #!/usr/bin/env bash
    set -euo pipefail
    git pull --ff-only
    pixi run test-worker
    url=$({{just_executable()}} neon-url)
    read -rp "Copy feeds, subscriptions, articles and read state from Cloudflare D1 now? [y/N] " copy
    if [[ "$copy" =~ ^[Yy] ]]; then
      DATABASE_URL="$url" pixi run migrate-d1
    fi
    # The first deploy signs in to FastAPI Cloud and creates (or links) the app;
    # the second picks up DATABASE_URL.
    uv run --frozen fastapi deploy
    uv run --frozen fastapi cloud env set --secret DATABASE_URL "$url"
    uv run --frozen fastapi deploy

# Print the pooled connection string of the Neon project named pulseboard
# (NEON_PROJECT for another name, NEON_PROJECT_ID for an id), signing in to
# Neon in the browser and creating the project if needed.
[private]
neon-url:
    #!/usr/bin/env bash
    set -euo pipefail
    neon() { npx --yes neonctl@8 --no-analytics "$@"; }
    neon me >/dev/null 2>&1 || neon login >&2
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
        echo "Creating the Neon project $name." >&2
        project=$(neon projects create --name "$name" -o json | pixi run -q python -c '
    import json, sys; d = json.load(sys.stdin); print((d.get("project") or d)["id"])')
      fi
    fi
    url=$(neon connection-string --project-id "$project" --pooled)
    [[ "$url" == postgres* ]] || { echo "Neon did not return a connection string: $url" >&2; exit 1; }
    echo "Using Neon project $project." >&2
    echo "$url"

# Copy the existing data from Cloudflare D1 into Neon (DATABASE_URL). Safe to run again.
migrate-d1:
    pixi run migrate-d1

# Quick FastAPI Cloud redeploy: pull main, test, deploy.
redeploy-fastapi:
    pixi run redeploy
