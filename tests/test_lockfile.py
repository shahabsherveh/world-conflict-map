"""Invariants of requirements.lock — the file the image and CI actually install.

These are offline checks on purpose: the point of the lock is that no network
resolution happens at install time, so the tests that guard it must not need one
either. Regenerating or diffing the lock (`scripts/lock-deps.sh --check`) does
need the index and is a maintenance command, not a per-commit gate.
"""

from __future__ import annotations

from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK = REPO_ROOT / "requirements.lock"
REQS = REPO_ROOT / "requirements.txt"


def _entries() -> list[str]:
    """Logical requirement lines: continuations joined, comments and index flags dropped."""
    joined: list[str] = []
    buffer = ""
    for raw in LOCK.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            # Comments sit between hash continuations; they must not end the entry.
            continue
        buffer = f"{buffer} {line}".strip() if buffer else line
        if buffer.endswith("\\"):
            buffer = buffer[:-1].strip()
            continue
        joined.append(buffer)
        buffer = ""
    if buffer:
        joined.append(buffer)
    return [entry for entry in joined if not entry.startswith("--")]


def _locked() -> dict[str, str]:
    locked: dict[str, str] = {}
    for entry in _entries():
        name, sep, rest = entry.partition("==")
        assert sep, f"unpinned lock entry: {entry}"
        locked[canonicalize_name(name)] = rest.split()[0]
    return locked


def _requirements() -> list[Requirement]:
    reqs = []
    for raw in REQS.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        reqs.append(Requirement(line))
    return reqs


def test_every_top_level_requirement_is_locked_and_satisfied() -> None:
    locked = _locked()
    for req in _requirements():
        name = canonicalize_name(req.name)
        assert name in locked, f"{name} is in requirements.txt but not the lock"
        version = Version(locked[name])
        assert version in req.specifier, (
            f"lock has {name}=={version}, which requirements.txt ({req.specifier}) rejects; "
            "re-run scripts/lock-deps.sh"
        )


def test_lock_pins_every_package_and_carries_its_hash() -> None:
    """Hash-checking mode is all-or-nothing, so one missing hash breaks the install."""
    entries = _entries()
    assert len(entries) > 50, f"lock looks truncated: only {len(entries)} packages"
    for entry in entries:
        assert "==" in entry, f"unpinned lock entry: {entry}"
        assert "--hash=sha256:" in entry, f"no hash for: {entry.split()[0]}"


def test_lock_pins_the_cpu_torch_build_and_declares_its_index() -> None:
    """The one install detail that must not regress: no CUDA wheel, ever.

    torch's `+cpu` build exists only on PyTorch's index, so the lock has to name
    that index for the install to resolve at all — a PyPI-only install would pick
    the multi-GB CUDA build.
    """
    text = LOCK.read_text()
    assert "--extra-index-url https://download.pytorch.org/whl/cpu" in text
    assert _locked()["torch"].endswith("+cpu")


def test_gate_tools_are_not_in_the_runtime_lock() -> None:
    """pytest and ruff are gate tools, pinned by hand in requirements-ci.txt.

    If they entered the runtime lock, a lock bump could silently change the tool
    version that decides pass/fail — which is the whole reason the two files are
    separate.
    """
    locked = _locked()
    for tool in ("pytest", "ruff", "ty", "pymarkdownlnt", "pip-audit"):
        assert canonicalize_name(tool) not in locked, (
            f"{tool} belongs in requirements-ci.txt, not the runtime lock"
        )
