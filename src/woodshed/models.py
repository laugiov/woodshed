"""Pretrained models (stems extra): kept in the woodshed cache, never downloaded in offline mode.

The libraries fetch weights through two channels, both guarded here:
- torch.hub (beat_this, and Demucs's legacy model repository);
- the Hugging Face Hub (Demucs 4.1 tries it first, then falls back to torch.hub).

The guard patches module attributes, so it is process-wide: one lock serialises the guarded
sections (model loading and separation are CPU-bound anyway), and nested use in one thread
keeps the outer setting.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

from woodshed.cache import cache_dir
from woodshed.errors import StemsError

OFFLINE_HINT = "is not downloaded yet: run once without --offline"
_lock = threading.RLock()
_active: list[bool] = []  # offline flag of each nested guard in the thread holding the lock


def offline_cause(exc: BaseException) -> StemsError | None:
    """Our offline refusal, when a library wrapped it in its own error (beat_this, Demucs do)."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, StemsError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


@contextmanager
def _torch_hub(offline: bool) -> Iterator[None]:
    import torch.hub

    # The private attribute is restored as it was: set_dir(get_dir()) would pin torch's default.
    had_dir, previous_dir = hasattr(torch.hub, "_hub_dir"), getattr(torch.hub, "_hub_dir", None)
    previous_get = torch.hub.get_dir()
    original = torch.hub.download_url_to_file

    def refuse(url: str, *args: Any, **kwargs: Any) -> None:
        raise StemsError(f"the model at {url} {OFFLINE_HINT}")

    torch.hub.set_dir(str(cache_dir() / "models"))
    if offline:
        torch.hub.download_url_to_file = refuse
    try:
        yield
    finally:
        torch.hub.download_url_to_file = original
        if had_dir:
            torch.hub._hub_dir = previous_dir
        else:
            torch.hub.set_dir(previous_get)


@contextmanager
def _hugging_face(offline: bool) -> Iterator[None]:
    try:
        import huggingface_hub
    except ImportError:  # only Demucs 4.1 and later use it
        yield
        return
    original = huggingface_hub.hf_hub_download
    folder = str(cache_dir() / "models" / "huggingface")

    def download(repo_id: str, filename: str, **kwargs: Any) -> str:
        kwargs.update(cache_dir=folder, local_files_only=offline)
        try:
            path: str = original(repo_id, filename, **kwargs)
        except FileNotFoundError as exc:  # LocalEntryNotFoundError: not in the cache
            if offline:
                raise StemsError(f"the model {repo_id}/{filename} {OFFLINE_HINT}") from exc
            raise
        return path

    # Demucs imports the function when it loads a model, so replacing the attribute is enough.
    huggingface_hub.hf_hub_download = download
    try:
        yield
    finally:
        huggingface_hub.hf_hub_download = original


@contextmanager
def torch_models(offline: bool) -> Iterator[None]:
    """Load models from the woodshed cache. In offline mode, any download attempt is an error."""
    with _lock:
        if _active:  # nested in this thread: the outer guard is already in place
            if offline != _active[0]:  # the inner caller would silently get the outer setting
                raise RuntimeError("a model guard cannot nest inside one with the other offline setting")
            _active.append(offline)
            try:
                yield
            finally:
                _active.pop()
            return
        _active.append(offline)
        try:
            with ExitStack() as stack:
                stack.enter_context(_torch_hub(offline))
                stack.enter_context(_hugging_face(offline))
                yield
        finally:
            _active.pop()
