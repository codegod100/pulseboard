# Pull main, then test, migrate and deploy the Worker.
deploy:
    pixi run deploy

# Pull main, test, then deploy the server to FastAPI Cloud.
deploy-cloud:
    pixi run deploy-cloud

# Set up FastAPI Cloud with Neon and deploy, start to finish. Asks for the Neon
# pooled connection string (or reads DATABASE_URL), offers to copy the existing
# data over from Cloudflare D1, stores the string on the app as a secret, and
# deploys. Safe to run again.
cloud:
    #!/usr/bin/env bash
    set -euo pipefail
    git pull --ff-only
    pixi run test-worker
    url="${DATABASE_URL:-}"
    if [[ -z "$url" ]]; then
      echo "Neon console > your project > Connect > tick 'Connection pooling' > copy the string."
      read -rsp "Neon pooled connection string (postgresql://…-pooler…): " url; echo
    fi
    [[ "$url" == postgres* ]] || { echo "That doesn't look like a Postgres connection string." >&2; exit 1; }
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
