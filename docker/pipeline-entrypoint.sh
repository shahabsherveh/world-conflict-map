#!/usr/bin/env sh
# One-shot entrypoint for the daily pipeline: apply migrations, then run the
# extraction pipeline. Extra args pass through, e.g.
#   docker compose run --rm pipeline --days 7
set -eu

alembic upgrade head
exec python -m app.extract.run "$@"
