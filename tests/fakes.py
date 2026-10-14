"""Stand-ins for the stems extra (torch.hub), so its adapters are tested without the 1.4 GB install."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest


def install_fake_torch(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A torch.hub that records its cache folder and downloads instead of touching the network."""
    state: dict[str, Any] = {"downloads": []}
    hub = types.ModuleType("torch.hub")
    hub.download_url_to_file = lambda url, *a, **k: state["downloads"].append(url)  # type: ignore[attr-defined]
    hub._hub_dir = None  # type: ignore[attr-defined]  # as in real torch: None until set_dir
    hub.get_dir = lambda: hub._hub_dir or "/default"  # type: ignore[attr-defined]  # torch: from TORCH_HOME
    hub.set_dir = lambda d: setattr(hub, "_hub_dir", d)  # type: ignore[attr-defined]
    torch = types.ModuleType("torch")
    torch.hub = hub  # type: ignore[attr-defined]
    torch.from_numpy = lambda a: a  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "torch.hub", hub)
    return state


def download(url: str) -> None:
    """What a library does to fetch its weights: always through the current torch.hub function."""
    sys.modules["torch.hub"].download_url_to_file(url, "/nonexistent/weights")


def install_fake_hugging_face(monkeypatch: pytest.MonkeyPatch, cached: set[str]) -> dict[str, Any]:
    """A huggingface_hub whose download returns cached files and records every call's options."""
    state: dict[str, Any] = {"calls": []}

    class LocalEntryNotFoundError(FileNotFoundError):  # as in huggingface_hub.errors
        pass

    def hf_hub_download(repo_id: str, filename: str, **kwargs: Any) -> str:
        state["calls"].append((repo_id, filename, kwargs))
        if kwargs.get("local_files_only") and filename not in cached:
            raise LocalEntryNotFoundError(filename)
        return f"{kwargs.get('cache_dir')}/{filename}"

    hub = types.ModuleType("huggingface_hub")
    hub.hf_hub_download = hf_hub_download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    return state


def hf_download(repo_id: str, filename: str) -> str:
    """What Demucs 4.1 does: import the function at call time, then call it."""
    from huggingface_hub import hf_hub_download

    path: str = hf_hub_download(repo_id, filename)
    return path


def hub_dir() -> str:
    """The folder the fake torch.hub would load models from right now."""
    folder: str = sys.modules["torch.hub"].get_dir()
    return folder
