#!/usr/bin/env bash
# Install this repository's GitHub Actions self-hosted runner, pinned to a
# runner release with a verified tarball hash.
#
# Registration needs a token from the repo's Settings -> Actions -> Runners ->
# New self-hosted runner page (valid ~1 hour). Pass it through RUNNER_TOKEN so
# it does not end up in shell history; --token works too and is warned about.
#
# Run as the user that will own the runner (not root):
#   sudo useradd -m -s /bin/bash ghrunner
#   sudo usermod -aG docker ghrunner          # image/deploy jobs need docker
#   sudo -iu ghrunner
#   cd /path/to/global-conflict-map
#   RUNNER_TOKEN=<from the UI> ./scripts/install-runner.sh --url https://github.com/OWNER/REPO
#
# The checkout/work directory is ~/actions-runner/_work. Never point the runner
# at a directory you edit by hand: actions/checkout runs `git clean -ffdx` and
# will delete untracked files (data/, *.db, .venv/).
set -euo pipefail

RUNNER_VERSION=v2.338.2
# From the release API; bump all three together and re-run --dry-run:
#   https://api.github.com/repos/actions/runner/releases/latest
RUNNER_SHA_X64=baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40
RUNNER_SHA_ARM64=670adb2f268fe21dcbb58b3db0e0aa9d5b3bddfe2c651481336e561ff86de945
runner_version="$RUNNER_VERSION"
sha_override=""

url=""
token="${RUNNER_TOKEN:-}"
name="$(hostname -s 2>/dev/null || hostname)"
labels=""
dir="${HOME}/actions-runner"
workdir="_work"
dry_run=0
force=0
allow_root=0

usage() {
  cat <<'EOF'
Install this repository's self-hosted GitHub Actions runner.

Usage: RUNNER_TOKEN=<token> scripts/install-runner.sh --url URL [options]

  --url URL        repository, e.g. https://github.com/OWNER/REPO (required)
  --token TOKEN    registration token (prefer RUNNER_TOKEN; this lands in history)
  --name NAME      runner name (default: short hostname)
  --labels LIST    extra labels, comma-separated; `self-hosted` is automatic
  --dir PATH       install directory (default: ~/actions-runner)
  --work NAME      work directory inside --dir (default: _work)
  --dry-run        download and verify the runner, print the config command,
                   change nothing (works without a token, even as root)
  --version VER    runner release to install (default: the pinned one)
  --sha256 HASH    expected archive hash for --version (required with it)
  --force          re-register over an existing ~/actions-runner/.runner
  --allow-root     permit a non-dry run as root (not recommended)
  -h, --help       this text

After configuring, the systemd service is installed and started when systemd is
present; otherwise the script prints the `./run.sh` command.
EOF
}

log() { printf '[runner] %s\n' "$*"; }
as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}
fail() {
  printf '[runner] error: %s\n' "$*" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --url) url="${2:?--url needs a value}"; shift 2 ;;
    --token) token="${2:?--token needs a value}"; shift 2 ;;
    --name) name="${2:?--name needs a value}"; shift 2 ;;
    --labels) labels="${2:?--labels needs a value}"; shift 2 ;;
    --dir) dir="${2:?--dir needs a value}"; shift 2 ;;
    --work) workdir="${2:?--work needs a value}"; shift 2 ;;
    --version) runner_version="${2:?--version needs a value}"; shift 2 ;;
    --sha256) sha_override="${2:?--sha256 needs a value}"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    --force) force=1; shift ;;
    --allow-root) allow_root=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) usage >&2; fail "unknown option: $1" ;;
  esac
done

case "$url" in
  https://github.com/*/*) ;;
  "") fail "--url is required (https://github.com/OWNER/REPO)" ;;
  *) fail "--url must look like https://github.com/OWNER/REPO (got: $url)" ;;
esac

if [ "$dry_run" -eq 0 ] && [ -z "$token" ]; then
  fail "no registration token; set RUNNER_TOKEN or pass --token (Settings -> Actions -> Runners)"
fi
if [ "$dry_run" -eq 0 ] && [ "$(id -u)" -eq 0 ] && [ "$allow_root" -eq 0 ]; then
  cat >&2 <<EOF
[runner] error: refusing to register as root: the service and every job would run
[runner]        with root plus docker access. Prefer a dedicated user:

  sudo useradd -m -s /bin/bash ghrunner
  sudo usermod -aG docker ghrunner
  sudo -iu ghrunner
  cd $(pwd)
  read -rs RUNNER_TOKEN && export RUNNER_TOKEN       # paste; no history
  ./scripts/install-runner.sh --url $url

[runner]        On a single-purpose host, --allow-root accepts the risk.
EOF
  exit 1
fi
if [ "$dry_run" -eq 0 ] && [ "$(id -u)" -eq 0 ]; then
  log "warning: --allow-root accepted; the runner service and every CI job will"
  log "warning: have root and docker access on this host"
fi
if [ -n "$token" ] && ! [ -t 0 ] && [ -z "${RUNNER_TOKEN:-}" ]; then
  log "note: --token is visible in shell history; prefer RUNNER_TOKEN=..."
fi

if [ -e "$dir/.runner" ] && [ "$force" -ne 1 ]; then
  fail "already configured ($dir/.runner); pass --force to re-register, or 'cd $dir && ./config.sh remove --token <token>'"
fi

if [ "$runner_version" != "$RUNNER_VERSION" ] && [ -z "$sha_override" ]; then
  fail "--version $runner_version needs its --sha256 (see the release API)"
fi
if [ -n "$sha_override" ] && [ "$runner_version" = "$RUNNER_VERSION" ]; then
  fail "--sha256 is only for a non-pinned --version; the pinned release has its hash"
fi
case "$(uname -m)" in
  x86_64)
    asset="actions-runner-linux-x64-${runner_version#v}.tar.gz"
    sha="${sha_override:-$RUNNER_SHA_X64}"
    ;;
  aarch64 | arm64)
    asset="actions-runner-linux-arm64-${runner_version#v}.tar.gz"
    sha="${sha_override:-$RUNNER_SHA_ARM64}"
    ;;
  *)
    fail "unsupported architecture $(uname -m); add its release hash to this script"
    ;;
esac

if command -v docker >/dev/null 2>&1; then
  if [ "$(id -u)" -ne 0 ] && ! id -nG | tr ' ' '\n' | grep -qx docker; then
    log "warning: $(id -un) is not in the docker group; the image and deploy jobs will fail"
    log "warning: fix with: sudo usermod -aG docker $(id -un)   (then re-login/restart the service)"
  fi
else
  log "warning: docker not found; the image and deploy jobs need it"
fi

install_dir="$dir"
if [ "$dry_run" -eq 1 ]; then
  install_dir=$(mktemp -d)
  trap 'rm -rf "$install_dir"' EXIT
fi
mkdir -p "$install_dir"

log "downloading $asset ($runner_version)"
curl -fsSL --retry 3 -o "$install_dir/runner.tar.gz" \
  "https://github.com/actions/runner/releases/download/${runner_version}/${asset}"
echo "${sha}  $install_dir/runner.tar.gz" | sha256sum -c -
tar -xzf "$install_dir/runner.tar.gz" -C "$install_dir"
rm -f "$install_dir/runner.tar.gz"

config_args=(--url "$url" --name "$name" --work "$workdir" --unattended)
[ -n "$labels" ] && config_args+=(--labels "$labels")
[ "$force" -eq 1 ] && config_args+=(--replace)

if [ "$dry_run" -eq 1 ]; then
  log "verified runner archive (sha256 ok)"
  log "dry run: would run in $dir:"
  log "  ./config.sh ${config_args[*]} --token <registration-token>"
  svc_cmd=""
  if [ "$(id -u)" -ne 0 ]; then svc_cmd="sudo "; fi
  log "  ${svc_cmd}./svc.sh install $(id -un) && ${svc_cmd}./svc.sh start"
  exit 0
fi

log "configuring runner '$name' for $url"
# The token is passed as an argument because config.sh has no env/stdio option;
# it is visible to same-user processes for the moment config.sh runs.
(
  cd "$install_dir"
  ./config.sh "${config_args[@]}" --token "$token"
)

if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
  (
    cd "$install_dir"
    as_root ./svc.sh install "$(id -un)"
    as_root ./svc.sh start
    as_root ./svc.sh status || true
  )
  log "installed as a systemd service; it starts on boot"
else
  log "no systemd here, so no service was installed. Start it in the foreground with:"
  log "  cd $install_dir && ./run.sh"
fi

log "registered. Push a branch and open a PR; the gates/image jobs should appear."
log "work dir: $install_dir/$workdir — keep it out of any directory you edit by hand."
