# CI/CD

Every change is verified by the same gates on every push, and `main` is deployed
automatically once those gates pass. The pipeline is deliberately small: gates that
are not run locally first tend to get bypassed.

Files:

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Lint, format, types, tests, migrations, artifact guard, image build + container smoke |
| `.github/workflows/deploy.yml` | Deploy the CI-verified commit to this host; roll back on an unhealthy start |
| `.github/dependabot.yml` | Weekly PRs for GitHub Actions and the UI-test npm deps |
| `requirements-ci.txt` | Exact ruff/ty versions the gates run (one source of truth) |
| `scripts/ci-check.sh` | The same gates, locally. `--docker` adds the image build |
| `scripts/deploy.sh` | Build → replace → readiness check → roll back (what the deploy job runs) |
| `scripts/_data-dir.sh` | The one definition of the deployed stack's data path |

## The gates

```
push / PR
   │
   ├─ gates (py3.11, the runtime we ship)
   │    ruff check                     unused imports, dead code, zip truncation
   │    ruff format --check            formatting is not a review topic
   │    ty check                       type errors, against 3.11
   │    pytest                         the full suite
   │    alembic upgrade head + check   revisions apply in order; models match migrations
   │    import app.main, …             the app starts without the model downloaded
   │    no tracked *.db/.env/.venv     second line of defence behind .gitignore
   │
   ├─ compat (py3.12, suite only)      requires-python is >=3.11; prove it
   │
   └─ image                            needs: gates
        docker build                  Dockerfile + full runtime deps
        compose config --quiet        compose file parses and interpolates
        import torch, transformers    the CPU wheels actually import
        run migrations + /health      the image serves before it is deployed
                │
                ▼
        push to main → deploy (workflow_run on CI success)
             checkout the exact commit CI verified
             build gcm-web:local, force-recreate web
             poll /health *and* require /api/conflicts to return JSON (30 × 2 s)
             not ready → re-tag previous image :rollback, recreate, verify
```

No gate can be skipped. A red gate is fixed, not silenced: no `# noqa` without a
reason in the comment, no `skip`ped test, no relaxed formatter.

The tools that decide pass/fail (`ruff`, `ty`) are pinned in `requirements-ci.txt`,
because an unpinned upgrade could turn a green branch red without a commit touching
it. `scripts/ci-check.sh` fails if the local versions drift from that file, so a
local pass means a pipeline pass.

### Why these and not more

- **No zero-shot model in CI.** The suite stubs the classifier; downloading ~570 MB
  would add minutes to every run and test nothing the adapter tests do not already
  cover. The stage that *would* need it (the daily pipeline) is not in CI by design —
  it depends on live GDELT and writes to the real database.
- **No `pip-audit` yet.** `requirements.txt` is unpinned, so an audit reports the
  resolver's current guesses, not what the image ships. Pin first (see Follow-ups).
- **The jsdom UI smoke test is not a gate.** It needs a running server and a seeded
  DB, and at world zoom its cluster-click check spiderfies, which jsdom cannot
  render without an SVG/canvas layer. It would be red for harness reasons, not app
  reasons. Run it by hand (`tests/ui/README.md`); `scripts/seed.py` now includes a
  no-location conflict so the panel is exercisable.

## Runner setup (self-hosted)

CI runs on the host that serves the app, because that is where the docker cache and
the compose stack live. One-time setup:

1. Install a self-hosted runner for this repo (Settings → Actions → Runners) with the
   label `self-hosted` (add `gcm` if you want to scope jobs explicitly later).
2. The runner user must be able to run `docker` without sudo (`usermod -aG docker
   $USER`, then re-login — a runner started before the group change keeps the old
   groups).
3. The runner's *working directory* must be writable and needs ~4 GB for images and
   the pip cache. **Do not point the runner at a directory you edit by hand:**
   `actions/checkout` runs `git clean -ffdx`, which deletes untracked files such as
   `data/`, `conflicts.db`, and `.venv/`. The compose file pins
   `name: global-conflict-map`, so whichever checkout the runner uses, it drives the
   same stack.
4. Create the deploy data directory, owned by the runner user:

   ```bash
   sudo install -d -o "$USER" -g "$USER" /var/lib/global-conflict-map/db
   ```

   `scripts/_data-dir.sh` sets `GCM_DATA_DIR` to it and is sourced by both
   `deploy.sh` and `docker-daily.sh` (which also creates the directory as the
   invoking user, so Docker does not make it root-owned), so the served app and the daily pipeline can
   never point at different databases. It is deliberately *not* duplicated in the
   workflow: that duplication is how the two drifted apart. Local `docker compose up`
   still uses `./data/db`. If the directory is missing, Docker creates it root-owned
   as the bind-mount target, and later pipeline runs cannot write the database.
5. No repository secrets are needed: the deploy uses local docker only.

### Security: a self-hosted runner runs the PR's code

`pull_request` executes the contribution's scripts on this host, with docker access.
Keep the repository **private**, and set Settings → Actions → General → "Require
approval for all outside collaborators" (or fork-PR workflows off). The deploy job is
not exposed: it triggers from `workflow_run` on `main` only, never from a PR.

### Branch protection (recommended)

- Require the `gates`, `compat` and `image` checks before merge.
- Require 1 approval, dismiss stale approvals, no force-pushes to `main`.
- Enable the `production` environment rule (Settings → Environments) if you want a
  manual approval gate on deploys; the workflow already references it. Leave it
  ungated for fully automatic deploys.

## Deploy and rollback

`deploy.yml` is triggered by `workflow_run` on a successful CI run for `main`, and
checks out `workflow_run.head_sha` — the commit CI verified, not whatever `main` is
now. A manual `workflow_dispatch` re-deploys the current `main`.

`scripts/deploy.sh`:

1. Tags the running image `gcm-web:rollback` **before** building. This must happen
   first: moving `gcm-web:local` prunes the old image ID, so tagging afterwards fails
   with `No such image`.
2. `docker compose build web pipeline`, then `up -d --no-deps --force-recreate web`.
   Forced because the tag does not change, so compose would otherwise leave the old
   container running. The pipeline image is built here as well: otherwise
   `docker compose run pipeline` builds it on demand from whichever checkout cron
   sits in, which need not be the commit CI tested.
3. Polls for 60 s until the stack is *ready*: `/health` answers (a static 200) **and**
   `/api/conflicts?start=1970-01-01&end=2100-01-01` returns a JSON array. The second
   check is the one that matters — a migration can leave the schema unreadable while
   `/health` stays green. `web` runs `alembic upgrade head` before `uvicorn`, so an
   upgrade that fails to start surfaces here too.
4. On failure, recreates from `gcm-web:rollback` and checks readiness again; the job
   still fails so the bad deploy is visible.

Manual rollback to the previous release:

```bash
GCM_IMAGE_TAG=rollback docker compose up -d --no-deps --force-recreate web
```

The rollback image name is derived from `docker compose config --images web`, not
hardcoded. That matters: with a `build:` section, compose *rebuilds* when the image
tag is missing, so a drifted rollback tag would silently start the new image again
while the log claimed a rollback.

Check what is deployed:

```bash
docker compose ps
curl -s http://127.0.0.1:8000/health
curl -s 'http://127.0.0.1:8000/api/conflicts?start=1970-01-01&end=2100-01-01'
```

Anything else that touches the stack (cron, a manual `docker compose` run) must use
the same `GCM_DATA_DIR`: source `scripts/_data-dir.sh`, or run through
`scripts/docker-daily.sh` / `scripts/deploy.sh`, which do it for you. The daily
script also forwards arguments, so `scripts/docker-daily.sh --days 7` is a real
backfill (a bare `docker compose run --rm pipeline` uses `./data/db` and used to
drop the flag).

Config is the one thing still read from the checkout the command runs in
(`./config/gdelt.yaml`). For the deployed stack that is the deploy checkout, so edit
and commit the config rather than editing a working copy and restarting.

The app is intentionally loopback-only (`127.0.0.1:8000`) and has no auth; never add
a public binding or a port-forward to this pipeline.

## Feeding failures back

Copy the failing step's output and fix the cause, then re-run the same gate locally:

| Failed gate | Local command |
|---|---|
| Lint / format | `ruff check . --fix && ruff format app tests scripts` |
| Types | `ty check` |
| Tests | `pytest -q -x` |
| Migrations | `GCM_DATABASE_URL=sqlite:////tmp/x.db alembic upgrade head && alembic check` |
| Image | `./scripts/ci-check.sh --docker` |

`./scripts/ci-check.sh` runs all non-docker gates in order.

## Follow-ups (not done here)

- **Pin dependencies.** `requirements.txt` is unpinned, so two CI runs can install
  different code. Compile a lock (`uv pip compile requirements.txt -o
  requirements.lock`), install from it in CI and in the Dockerfile, and add the `pip`
  ecosystem back to `dependabot.yml`. This is a dependency decision, hence not
  bundled with the pipeline.
- **Dependabot for pip** becomes possible only after pinning.
- **UI smoke as a gate** once it has a fixture seed dense enough for its viewport
  checks (it now passes except the "list narrows" check on demo data).
- **Retention/monitoring**: the deploy job records health, but nothing alerts if the
  container dies later (`restart: unless-stopped` covers crashes, not failure loops).
