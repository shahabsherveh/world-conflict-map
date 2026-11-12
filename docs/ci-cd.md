# CI/CD

Every change is verified by the same gates on every push, and `main` is deployed
automatically once those gates pass. The pipeline is deliberately small: gates that
are not run locally first tend to get bypassed.

Files:

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Lint, format, shellcheck, markdown, types, tests, migrations, artifact guard, image build + container smoke |
| `.github/workflows/deploy.yml` | Deploy the CI-verified commit to this host; roll back on an unhealthy start |
| `.github/dependabot.yml` | Weekly PRs for GitHub Actions and the UI-test npm deps |
| `requirements-ci.txt` | Exact ruff/ty/pymarkdown versions the gates run (one source of truth) |
| `scripts/ci-check.sh` | The same gates, locally. `--docker` adds the image build |
| `scripts/git-hooks/pre-commit` | Runs `scripts/ci-check.sh` on commit; activated by `scripts/install-hooks.sh` |
| `scripts/install-hooks.sh` | Points `core.hooksPath` at the tracked hooks directory |
| `scripts/deploy.sh` | Build → replace → readiness check → roll back (what the deploy job runs) |
| `scripts/install-runner.sh` | Register this repo's self-hosted runner (pinned release, verified hash) |
| `scripts/cutover-data.sh` | One-time, WAL-safe move of an existing DB into `GCM_DATA_DIR` |
| `scripts/_data-dir.sh` | The one definition of the deployed stack's data path |
| `scripts/_venv.sh` | The one definition of where the local venv lives (`GCM_VENV`) |

## The gates

```text
push / PR
   │
   ├─ gates (py3.12, the runtime we ship)
   │    uv provisions CPython 3.12     setup-python has no Debian builds
   │    installs ruff/ty/pytest        inside the venv step, then prints versions
   │    ruff check                     unused imports, dead code, zip truncation
   │    ruff format --check            formatting is not a review topic
   │    shellcheck scripts/*.sh        deploy/rollback/cutover scripts
   │    pymarkdown scan                docs structure, bare URLs, broken fences
   │    ty check                       type errors, against 3.12
   │    pytest                         the full suite
   │    alembic upgrade head + check   revisions apply in order; models match migrations
   │    import app.main, …             the app starts without the model downloaded
   │    no tracked *.db/.env/.venv     second line of defence behind .gitignore
   │
   └─ image                            needs: gates
        docker build --network=host   Dockerfile + full runtime deps (see below)
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

The tools that decide pass/fail (`ruff`, `ty`, `pymarkdown`) are pinned in
`requirements-ci.txt`, because an unpinned upgrade could turn a green branch red
without a commit touching it. `scripts/ci-check.sh` fails if the local versions drift
from that file, so a local pass means a pipeline pass.

### Why these and not more

- **Every build path builds on the host network.** Expressed once, as
  `network: host` under each service's `build:` in `docker-compose.yml`, so the CI
  image job (`docker build --network=host`), `scripts/deploy.sh` (compose build) and
  cron all agree. Verify with a container that resolves PyPI badly and a control
  build without the key — the control fails in ~12 s on this host.
- **The image build runs with `--network=host`.** Build steps execute in a container
  on the default bridge, and Docker replaces that container's resolver with its own
  defaults (`8.8.8.8`/`8.8.4.4` in this environment — "Used default nameservers").
  Those are unreachable here, so pip stalls on `files.pythonhosted.org` with a
  `ReadTimeoutError`, while the gates job — running on the runner's own resolver —
  installs the same packages fine. Host networking borrows the resolver that works.
  The durable fix is `"dns": [...]` in the Docker daemon config on the deploy host;
  until that is set there, the flag is required, not cosmetic.
- **Python comes from uv, not `actions/setup-python`.** setup-python only ships
  Ubuntu/macOS/Windows builds, and the self-hosted runner is Debian: every job failed
  with "version ... was not found for debian 12". `.github/actions/uv-python`
  installs a pinned uv (per-arch sha256, like shellcheck) and creates the venv from a
  uv-managed CPython, cached in `~/.local/share/uv` across runs.
- **One venv location, shared by design.** CI builds its venv at
  `$GITHUB_WORKSPACE/.venv` — the same relative path `scripts/_venv.sh` defaults to
  — so the CI environment and a developer's environment are the same *shape*. It is
  gitignored and re-created every run; `git clean` happens before it exists and the
  artifact guard only inspects tracked files.
- **Scripts resolve their interpreter and tools by absolute path.** No script
  assumes it was started from the repo root or that `.venv` is already on PATH:
  `scripts/_venv.sh` owns the venv location (`GCM_VENV` overrides it) and the
  callers use `"$(gcm_venv_python)"` / `"$(gcm_venv_tool ruff)"`. CI does the same
  with `$RUNNER_TEMP/venv/bin/...` and asserts the tools exist before the gates
  run, because a `command not found` and a lint failure look identical in a
  runner log.
- **Downloaded tools are invoked by absolute path, never via `$GITHUB_PATH`.** A
  persistent PATH entry outlives `$RUNNER_TEMP`: after a job ends the directory is
  gone, and the next job either gets a dangling entry or resolves a same-named binary
  elsewhere. That happened — the shellcheck step failed in 0.4 s with no output —
  so `UV_BIN`/`SHELLCHECK_BIN` go through `$GITHUB_ENV`, and the shellcheck step
  prints `--version` first so the log names the binary it ran.
- **Shellcheck policy lives in `.shellcheckrc`, not in flags.** `external-sources=true`
  makes shellcheck follow `source .venv/bin/activate` and the shared
  `scripts/_data-dir.sh`; without it, a plain `shellcheck scripts/daily.sh` reports
  SC1091 and exits 1, which is exactly what someone running the tool by hand sees.
  CI and `scripts/ci-check.sh` run the plain command so all three agree.
- **Shellcheck is pinned by version and per-arch tarball hash.** The deploy, rollback and
  cutover scripts are the highest-consequence code in the repo and nothing else parses
  them: actionlint checks only the `run:` blocks embedded in workflows. CI downloads
  v0.11.0 into `$RUNNER_TEMP` and verifies the sha256 before running it;
  `scripts/ci-check.sh` reads that same `SHELLCHECK_VERSION` out of the workflow and
  uses either a local binary at exactly that version or the Docker image at that tag
  (`koalaman/shellcheck:v0.11.0`), so the gate also runs outside CI without drifting.
  A local binary at another version is not silently used: the pinned image takes over
  and the reason is printed. `:stable` is deliberately not used — it has drifted past
  the tarball CI verifies, which would make shell-script findings depend on the day.

- **No zero-shot model in CI.** The suite stubs the classifier; downloading ~570 MB
  would add minutes to every run and test nothing the adapter tests do not already
  cover. The stage that *would* need it (the daily pipeline) is not in CI by design —
  it depends on live GDELT and writes to the real database.
- **Markdown is gated with `pymarkdown`.** It catches broken fences, bare URLs,
  duplicate headings, and overlong prose. MD022/MD032/MD036/MD060 are disabled in
  `pyproject.toml`: the docs' valid GFM style (a heading or bold label immediately
  followed by a list, compact `|---|` tables) would otherwise need a mass reformat
  that changes no rendered output.
- **No `pip-audit` yet.** `requirements.txt` is unpinned, so an audit reports the
  resolver's current guesses, not what the image ships. Pin first (see Follow-ups).
- **The UI harnesses are not gates.** `map-smoke.mjs` needs a running server with a
  *populated* DB (any density works; an empty one cannot anchor its time-scrub window)
  and npm to install jsdom.
  `browser-tests.mjs` additionally needs Chrome on `:9222` and network for tiles. The
  runner is not guaranteed to have either — a rebuilt or mock runner has no Chrome
  until someone installs it — so do not promote it to a gate. Run
  them by hand (`tests/ui/README.md`); `scripts/seed.py` includes a no-location conflict
  so the panel is exercisable and offsets coordinates to avoid spiderfy.

## Runner setup (self-hosted)

CI runs on the host that serves the app, because that is where the docker cache and
the compose stack live. One-time setup:

1. Create the runner account and give it docker (a runner started before the group
   change keeps the old groups, so re-login or restart the service):

   ```bash
   sudo useradd -m -s /bin/bash ghrunner
   sudo usermod -aG docker ghrunner
   ```

2. Mint a registration token: **Settings → Actions → Runners → New self-hosted
   runner** (valid ~1 hour). Then install, as `ghrunner`:

   ```bash
   sudo -iu ghrunner
   cd /path/to/global-conflict-map
   RUNNER_TOKEN=<from the UI> ./scripts/install-runner.sh \
     --url https://github.com/OWNER/REPO
   ```

   The script downloads a pinned runner release (v2.338.2) into `~/actions-runner`,
   verifies the tarball's sha256 for x86_64/arm64, configures it, and installs and
   starts the systemd service when systemd is present. `--dry-run` downloads and
   verifies without registering (no token needed); `--version`/`--sha256` bump the
   pin; `--force` re-registers over an existing `~/actions-runner/.runner`.

   Read the token with `read -rs RUNNER_TOKEN` rather than pasting it into a command:
   it is reusable until it expires, so treat a token that appeared in a transcript as
   burned and mint another.

   `--allow-root` exists for hosts where root is the only account: without it the
   script refuses, because the service and every job then run with root plus docker
   access. The service install no longer assumes `sudo` exists, so `--allow-root`
   works on a root-only host.

   Manual alternative: download from the UI and run `./config.sh --url … --token …`.
   The default `self-hosted` label is what the workflows use; `--labels gcm` scopes
   them to this runner if you ever add more.

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

### First deploy: bring the existing database across

The deployed stack reads `GCM_DATA_DIR` (default `/var/lib/global-conflict-map/db`),
not `./data/db`, and the project name is pinned to `global-conflict-map`. Without a
cutover, an old `workspace` stack keeps port 8000 and the new app starts on an empty DB
that looks like data loss. `scripts/cutover-data.sh` moves the data; dry-run first:

```bash
docker compose ls -a                     # find the old project, if any
docker compose -p workspace down         # only if it exists

./scripts/cutover-data.sh                # prints source, row counts and target
./scripts/cutover-data.sh --apply --owner "$USER"
```

What it guarantees, each rehearsed against a synthetic DB:

- **WAL-safe.** It uses SQLite's backup API, not `cp`; a writer holding committed pages
  in a `-wal` file is included. (Rehearsed with the writer still connected: the row
  copied, and `cp` of the main file alone would have missed it.)
- **Verified.** Runs `pragma integrity_check` and compares `conflict`/`conflict_event`
  counts on the copy; unequal counts fail the run.
- **Non-destructive.** An existing target is renamed `conflicts.db.bak-<timestamp>`
  (`--force` required); the old database is never deleted.
- **Cache-aware.** Copies `<source dir>/hf-cache` when present, avoiding a ~570 MB
  re-download on the first pipeline run. That is the *only* model cache both the
  container (`HF_HOME=/data/hf-cache`) and the host pipeline use — `daily.sh`
  sources `scripts/_data-dir.sh`, which exports `HF_HOME="$GCM_DATA_DIR/hf-cache"`.
  If the host cannot reach `cdn-lfs.huggingface.co` (downloads stall as
  `*.incomplete`), copy a finished cache from another machine into
  `$GCM_DATA_DIR/hf-cache/hub/` and verify with
  `python scripts/download_model.py --check`.
- **Refuses unsafe runs.** Wrong-schema file, missing source, or a running container
  that mounts the target directory all abort before writing.

Then `docker compose up -d --build` (or let the first CI deploy do it) and confirm
`/api/conflicts` returns the counts the script printed.

### Branch protection (recommended)

- Require the `gates` and `image` checks before merge.
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
2. `docker compose build web pipeline` — the compose file sets `network: host` on both
   builds (build-container DNS, see below), with `docker build --network=host` as a
   fallback for compose versions that ignore the key. Then
   `up -d --no-deps --force-recreate web`.
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

### Monitoring after the deploy

`restart: unless-stopped` covers a crash, not a container that comes up and then
fails every request, and the deploy job only checks readiness once. Two host-side
watchers cover the gap; install both with cron or a systemd timer:

- `scripts/check-health.sh` — the *same* readiness definition as `deploy.sh`
  (`/health` 200 **and** `/api/conflicts` returns a JSON array), exits non-zero so
  cron's `MAILTO` or systemd's `OnFailure` reaches a human.
- `scripts/install-health-watch.sh` — installs a 15-minute `gcm-health-check.timer`
  that runs it (`--dry-run` prints the units, `--remove` uninstalls).
- `scripts/check-pipeline.sh` — the other half of the picture: the app can be up while
  the *data* has stopped updating (gotcha #9 in `AGENTS.md`). It reads
  `/api/pipeline-health` and exits non-zero when the last successful run is older than
  `pipeline_stale_hours`.

```bash
sudo ./scripts/install-health-watch.sh          # app is answering
# and in the crontab, for the data:
0 8 * * * /path/to/repo/scripts/check-pipeline.sh
```

Anything else that touches the stack (cron, a manual `docker compose` run) must use
the same `GCM_DATA_DIR`: source `scripts/_data-dir.sh`, or run through
`scripts/docker-daily.sh` / `scripts/deploy.sh`, which do it for you. The daily
script also forwards arguments, so `scripts/docker-daily.sh --days 7` is a real
backfill (a bare `docker compose run --rm pipeline` uses `./data/db` and used to
drop the flag).

Config follows the same rule as data: `scripts/_data-dir.sh` defines
`GCM_CONFIG_DIR` (default `./config`) and both compose services mount
`$GCM_CONFIG_DIR/gdelt.yaml`. For the deployed stack that resolves to the deploy
checkout, which is disposable — the next deploy's `git clean -ffdx` removes any hand
edit. Change config in git, not in a working copy that you then restart.

A docs-only push does not deploy. `workflow_run` cannot use `paths-ignore` (it is
evaluated against the CI run's event, not this one), so the deploy job diffs
`HEAD^..HEAD` and skips the build when every changed file is a `*.md` or under
`docs/`, `tasks/`, `.agents/`. A shallow clone or a manual run always deploys.

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

## Commit-time gates

`./scripts/install-hooks.sh` sets `core.hooksPath` to `scripts/git-hooks/`, so the
hook is versioned and reviewed like any other file instead of living in the
untracked `.git/hooks/`. `scripts/git-hooks/pre-commit` is a thin wrapper on
`scripts/ci-check.sh` — one definition of the gate list, not two that can drift.

The hook is opt-in per clone, because git deliberately never runs hooks it did not
find configured; run the installer once after cloning. `git commit --no-verify`
skips it (documented, not accidental: pytest at commit time is slow for a WIP
checkpoint, and CI still enforces the bar on push).

The installer refuses to arm the hook unless the venv and the pinned tools exist,
so a cold clone fails at install time with the exact fix instead of at the next
commit. The gates themselves resolve every tool through `scripts/_venv.sh`, so they
do not depend on the venv being activated on PATH.

### What the hook does not cover

A green hook is not the same guarantee as a green pipeline. Known gaps, all caught
by CI on push, none by the hook:

- **The working tree, not the index.** Partial staging (`git add -p`) can commit a
  blob that would fail while the worktree the hook inspected passes, and an
  unrelated dirty file with a lint error blocks a commit that does not include it.
- **`cherry-pick` and `revert` do not run `pre-commit`**, and merges run
  `pre-merge-commit`, which the repo does not define. Those commits skip the gate
  entirely.
- **A moved checkout silently disables it.** `core.hooksPath` is an absolute path;
  if the directory no longer exists, git ignores the missing hook and commits
  normally. Re-run `./scripts/install-hooks.sh` after moving or renaming the repo.

## Follow-ups (not done here)

- **First hosted run.** The workflows are validated so far only by actionlint and by
  running each command locally; the first PR exercises `workflow_run`,
  `$GITHUB_PATH`, uv's interpreter cache and the deploy rollback on the real runner.
  Keep the `production` environment ungated until that passes.
- **Pin the runtime dependencies (needs a decision).** `requirements.txt` is still
  unpinned, so the image and CI install whatever the resolver picks that day. The gate
  tools are pinned in `requirements-ci.txt`, which is what protects a green commit from
  being reddened by a release; the runtime is not. Fixing that means committing a
  lock file and installing from it in the Dockerfile — a dependency decision, so it is
  deliberately left open. Until then there is no `pip-audit` gate and no pip ecosystem
  in `dependabot.yml`: an audit against unpinned requirements reports guesses.
- **The UI harnesses stay out of CI by decision.** `map-smoke.mjs` now tolerates any
  populated fixture (dense, demo, or the real DB) and reports `SKIPPED` where a fixture
  cannot demonstrate a check, so its data-density caveat is gone. It is still not a
  gate: the runner has neither npm nor Chrome installed and may be rebuilt, and the
  browser suite additionally needs network for tiles. See the note under "The gates".
- **Retention**: image layers and buildkit cache accumulate and nothing prunes them.
  A monthly `docker image prune -f --filter until=168h` and
  `docker builder prune -f --filter until=168h` keeps disk usage flat.
