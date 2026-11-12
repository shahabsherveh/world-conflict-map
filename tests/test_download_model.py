"""The model-cache check behind `scripts/download_model.py --check`.

Covers the behaviour that made the model look like it "keeps downloading": a
cache with only config/ONNX files is not usable by transformers, and a cache with
*either* weight file is. Both directions must hold, or the check either passes on
an unusable cache or re-downloads after a good copy.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_model.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("download_model", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def model_cache(tmp_path, monkeypatch):
    """Point HF_HOME at a temp dir and return (module, snapshot dir factory)."""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    module = _load_module()
    model_dir = tmp_path / "hub" / "models--cross-encoder--nli-deberta-v3-small"

    def snapshot(files: list[str]) -> Path:
        snap = model_dir / "snapshots" / "rev1"
        snap.mkdir(parents=True)
        for name in files:
            path = snap / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
        return model_dir

    return module, snapshot


def test_missing_when_cache_absent(model_cache):
    module, _ = model_cache
    assert module.has_weights() is False


def test_config_only_is_not_enough(model_cache):
    # The regression: config + ONNX present, weights absent, used to look "ready".
    module, snapshot = model_cache
    snapshot(["config.json", "tokenizer.json", "onnx/model_O3.onnx"])
    assert module.has_weights() is False


def test_pytorch_bin_counts_as_complete(model_cache):
    module, snapshot = model_cache
    snapshot(["config.json", "pytorch_model.bin"])
    assert module.has_weights() is True


def test_safetensors_counts_as_complete(model_cache):
    module, snapshot = model_cache
    snapshot(["config.json", "model.safetensors"])
    assert module.has_weights() is True


def test_check_mode_exits_nonzero_without_weights(model_cache, capsys):
    module, snapshot = model_cache
    snapshot(["config.json"])
    assert module.main(["--check"]) == 1
    assert "no PyTorch weights" in capsys.readouterr().err


def test_check_mode_exit_zero_with_weights(model_cache):
    module, snapshot = model_cache
    snapshot(["model.safetensors"])
    assert module.main(["--check"]) == 0


def test_incomplete_blobs_are_reported(model_cache):
    module, snapshot = model_cache
    model_dir = snapshot(["config.json"])
    blobs = model_dir / "blobs"
    blobs.mkdir()
    (blobs / "abc.incomplete").write_bytes(b"x")
    assert [p.name for p in module.incomplete_blobs()] == ["abc.incomplete"]


def test_warns_when_hf_home_unset(model_cache, monkeypatch, capsys):
    module, _ = model_cache
    monkeypatch.delenv("HF_HOME", raising=False)
    module.warn_if_default_cache()
    assert "HF_HOME is not set" in capsys.readouterr().err


def test_silent_when_hf_home_set(model_cache, capsys):
    # model_cache sets HF_HOME; no warning means the shared cache is in use.
    module, _ = model_cache
    module.warn_if_default_cache()
    assert capsys.readouterr().err == ""
