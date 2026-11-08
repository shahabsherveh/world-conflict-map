#!/usr/bin/env bash
# Move an existing SQLite database (and HF model cache) into GCM_DATA_DIR,
# before the first CI deploy.
#
# Dry-run by default: it reads the source, prints the plan and the row counts.
# `--apply` performs the copy. The target is never overwritten silently: an
# existing target is renamed to conflicts.db.bak-<UTC timestamp> and --force is
# required to proceed. Nothing is ever deleted.
#
# Why not `cp`: the source may be in WAL mode with committed pages still in the
# -wal file, so a file copy can lose the newest rows. This uses SQLite's backup
# API, which is consistent for any journal mode, then verifies integrity and
# row counts on the copy.
set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck source=scripts/_data-dir.sh
source scripts/_data-dir.sh

dry_run=1
force=0
owner=""
src=""
dst=""

usage() {
  cat <<'EOF'
Cut over the host database to GCM_DATA_DIR.

Usage: scripts/cutover-data.sh [options]

  --from PATH    source DB (default: data/db/conflicts.db, else ./conflicts.db)
  --to PATH      target DB (default: $GCM_DATA_DIR/conflicts.db)
  --owner USER   chown the target directory to USER after copying
  --apply        perform the copy (default: read-only dry run)
  --force        replace an existing target, after renaming it to a .bak
  -h, --help     this text

The old database is never deleted. Verify the API's counts after deploying,
then retire it yourself.
EOF
}

log() { printf '[cutover] %s\n' "$*"; }
fail() {
  printf '[cutover] error: %s\n' "$*" >&2
  exit 1
}

# Prints integrity + row counts for a DB, read-only. Exit 3 if the schema is not
# a conflict DB, so a wrong path fails before anything is written.
db_stats() {
  "$PYTHON_BIN" - "$1" <<'PY'
import sqlite3
import sys
import urllib.parse

path = sys.argv[1]
con = sqlite3.connect("file:" + urllib.parse.quote(path) + "?mode=ro", uri=True)
try:
    integrity = con.execute("pragma integrity_check").fetchone()[0]
    tables = {row[0] for row in con.execute("select name from sqlite_master where type='table'")}
    missing = sorted({"conflict", "conflict_event"} - tables)
    if missing:
        print("missing tables: " + ", ".join(missing), file=sys.stderr)
        raise SystemExit(3)
    counts = {}
    for table in ("conflict", "conflict_event", "raw_event"):
        if table in tables:
            counts[table] = con.execute(f"select count(*) from {table}").fetchone()[0]
finally:
    con.close()
print(f"integrity={integrity}")
for table, count in counts.items():
    print(f"{table}={count}")
PY
}

while [ $# -gt 0 ]; do
  case "$1" in
    --from) src="${2:?--from needs a path}"; shift 2 ;;
    --to) dst="${2:?--to needs a path}"; shift 2 ;;
    --owner) owner="${2:?--owner needs a user}"; shift 2 ;;
    --apply) dry_run=0; shift ;;
    --force) force=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) usage >&2; fail "unknown option: $1" ;;
  esac
done

if [ -x .venv/bin/python ]; then
  PYTHON_BIN=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
else
  fail "no python3 found; it is needed for the WAL-safe copy"
fi

if [ -z "$src" ]; then
  for candidate in data/db/conflicts.db conflicts.db; do
    if [ -f "$candidate" ]; then
      src=$candidate
      break
    fi
  done
fi
[ -n "$src" ] || fail "no source DB found (looked for data/db/conflicts.db, ./conflicts.db); pass --from PATH"
[ -f "$src" ] || fail "source not found: $src"
src=$(readlink -f "$src")

dst="${dst:-$GCM_DATA_DIR/conflicts.db}"
dst_dir=$(dirname "$dst")
dst_dir_real=$(realpath -m "$dst_dir")
cache_src="$(dirname "$src")/hf-cache"
cache_dst="$dst_dir/hf-cache"

if [ -n "$owner" ] && ! id "$owner" >/dev/null 2>&1; then
  fail "no such user for --owner: $owner"
fi

# Guard: data inside the checkout is deleted by `actions/checkout`'s
# `git clean -ffdx` on the next CI run.
repo_root=$(pwd)
case "$dst_dir_real/" in
  "$repo_root"/*)
    log "warning: target is inside the repository; a CI checkout runs 'git clean -ffdx'"
    log "warning: and would delete $dst_dir_real — prefer the GCM_DATA_DIR default"
    ;;
esac

src_stats=$(db_stats "$src") || fail "source is not a usable conflict DB: $src"
src_integrity=$(printf '%s\n' "$src_stats" | sed -n '1s/^integrity=//p')
src_counts=$(printf '%s\n' "$src_stats" | tail -n +2 | tr '\n' ' ')
[ "$src_integrity" = "ok" ] || fail "source failed 'pragma integrity_check': $src_integrity"

# Guard: a running container with this directory (or a parent of it) mounted
# would keep writing to the old file while the new one is copied.
in_use=""
if command -v docker >/dev/null 2>&1; then
  while read -r id; do
    [ -n "$id" ] || continue
    while IFS= read -r mount; do
      [ -n "$mount" ] || continue
      mount_real=$(realpath -m "$mount")
      case "$dst_dir_real/" in
        "$mount_real"/*)
          in_use="$in_use $(docker inspect --format '{{.Name}}' "$id" 2>/dev/null | sed 's|^/||')"
          break
          ;;
      esac
    done < <(docker inspect --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$id" 2>/dev/null || true)
  done < <(docker ps -q 2>/dev/null || true)
fi
if [ -n "$in_use" ]; then
  log "containers currently mount $dst_dir_real:$in_use"
  [ "$dry_run" -eq 1 ] || fail "stop them first (docker compose -p <project> down), then re-run"
fi

log "source: $src"
log "        $(du -h "$src" | cut -f1), $src_counts"
log "target: $dst"
if [ -e "$dst" ]; then
  if [ "$force" -eq 1 ]; then
    log "        exists; will be renamed to $(basename "$dst").bak-<timestamp>"
  else
    log "        exists; --apply needs --force to replace it"
  fi
else
  log "        does not exist yet"
fi
if [ -d "$cache_src" ]; then
  log "cache:  $cache_src -> $cache_dst"
else
  log "cache:  none at $cache_src (the pipeline will download the model)"
fi
[ -n "$owner" ] && log "owner:  $owner"

if [ "$dry_run" -eq 1 ]; then
  log "dry run: nothing written. Re-run with --apply to copy."
  exit 0
fi

if [ -e "$dst" ] && [ "$force" -ne 1 ]; then
  fail "target already exists: $dst (pass --force to back it up and replace)"
fi

mkdir -p "$dst_dir" || fail "cannot create $dst_dir (run with sudo, or pass --to a writable path)"

if [ -e "$dst" ]; then
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  for suffix in "" "-wal" "-shm"; do
    if [ -e "$dst$suffix" ]; then
      mv "$dst$suffix" "$dst.bak-$stamp$suffix"
    fi
  done
  log "existing target preserved at $dst.bak-$stamp"
fi

"$PYTHON_BIN" - "$src" "$dst" <<'PY'
import sqlite3
import sys
import urllib.parse

source_path, target_path = sys.argv[1], sys.argv[2]
source = sqlite3.connect("file:" + urllib.parse.quote(source_path) + "?mode=ro", uri=True)
target = sqlite3.connect(target_path)
try:
    with target:
        source.backup(target)
finally:
    target.close()
    source.close()
PY

dst_stats=$(db_stats "$dst") || fail "copied DB is unusable; source is untouched"
if [ "$dst_stats" != "$src_stats" ]; then
  fail "verification failed — source: $src_stats / target: $dst_stats"
fi
log "verified: $(printf '%s' "$src_stats" | tr '\n' ' ')"

if [ -d "$cache_src" ] && [ ! -e "$cache_dst" ]; then
  cp -a "$cache_src" "$cache_dst"
  log "copied model cache to $cache_dst"
fi

if [ -n "$owner" ]; then
  chown -R "$owner:$owner" "$dst_dir"
  log "owner set to $owner"
fi

log "done. next: docker compose up -d --build (or merge and let Deploy run)"
log "the old DB at $src is untouched; retire it after the API returns these counts."
