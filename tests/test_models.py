"""Model downloads (stems extra): both channels go to the woodshed cache and are refused offline."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.fakes import download, hf_download, hub_dir, install_fake_hugging_face, install_fake_torch
from woodshed.errors import StemsError
from woodshed.models import offline_cause, torch_models


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path))
    return tmp_path


def test_hugging_face_downloads_go_to_our_cache(monkeypatch: pytest.MonkeyPatch, cache: Path) -> None:
    install_fake_torch(monkeypatch)
    state = install_fake_hugging_face(monkeypatch, cached=set())
    with torch_models(offline=False):
        path = hf_download("adefossez/HTDemucs", "htdemucs.yaml")
    _, _, options = state["calls"][0]
    assert options == {"cache_dir": str(cache / "models" / "huggingface"), "local_files_only": False}
    assert path.startswith(str(cache))


def test_offline_hugging_face_uses_only_local_files(monkeypatch: pytest.MonkeyPatch, cache: Path) -> None:
    install_fake_torch(monkeypatch)
    install_fake_hugging_face(monkeypatch, cached={"htdemucs.yaml"})
    with torch_models(offline=True):
        assert hf_download("adefossez/HTDemucs", "htdemucs.yaml")  # already downloaded: fine
        with pytest.raises(StemsError, match="--offline"):
            hf_download("adefossez/HTDemucs", "955717e8.safetensors")


def test_offline_torch_hub_refuses_and_everything_is_restored(monkeypatch: pytest.MonkeyPatch, cache: Path) -> None:
    torch_state = install_fake_torch(monkeypatch)
    install_fake_hugging_face(monkeypatch, cached=set())
    import huggingface_hub
    import torch.hub

    before = (torch.hub.download_url_to_file, huggingface_hub.hf_hub_download)
    with torch_models(offline=True), pytest.raises(StemsError, match="--offline"):
        download("https://example.org/final0.ckpt")
    assert torch_state["downloads"] == [] and hub_dir() == "/default" and sys.modules["torch.hub"]._hub_dir is None
    assert (torch.hub.download_url_to_file, huggingface_hub.hf_hub_download) == before


def test_a_refusal_wrapped_by_a_library_is_found() -> None:
    refusal = StemsError("the model final0 is not downloaded yet: run once without --offline")
    try:
        try:
            raise refusal
        except StemsError as inner:
            raise ValueError("Could not load the checkpoint given the provided name") from inner
    except ValueError as wrapped:
        assert offline_cause(wrapped) is refusal
    assert offline_cause(RuntimeError("unrelated")) is None


def test_guards_used_from_two_threads_restore_everything(monkeypatch: pytest.MonkeyPatch, cache: Path) -> None:
    import threading

    torch_state = install_fake_torch(monkeypatch)
    install_fake_hugging_face(monkeypatch, cached=set())
    import torch.hub

    original = torch.hub.download_url_to_file
    entered, release = threading.Event(), threading.Event()

    def offline_worker() -> None:
        with torch_models(offline=True):
            entered.set()
            release.wait(5)

    worker = threading.Thread(target=offline_worker)
    worker.start()
    entered.wait(5)
    online_done = threading.Event()

    def online_worker() -> None:
        with torch_models(offline=False):  # waits for the offline section to finish
            download("https://example.org/allowed.ckpt")
        online_done.set()

    second = threading.Thread(target=online_worker)
    second.start()
    assert not online_done.wait(0.2)  # serialised, not interleaved
    release.set()
    worker.join(5)
    second.join(5)
    assert online_done.is_set() and torch_state["downloads"] == ["https://example.org/allowed.ckpt"]
    assert (
        torch.hub.download_url_to_file is original
        and hub_dir() == "/default"
        and sys.modules["torch.hub"]._hub_dir is None
    )


def test_nested_guards_keep_the_outer_setting(monkeypatch: pytest.MonkeyPatch, cache: Path) -> None:
    install_fake_torch(monkeypatch)
    install_fake_hugging_face(monkeypatch, cached=set())
    with torch_models(offline=True):
        with torch_models(offline=True), pytest.raises(StemsError):
            download("https://example.org/x.ckpt")
        with pytest.raises(StemsError):  # still offline after the inner guard exits
            download("https://example.org/x.ckpt")
    for outer, inner in ((False, True), (True, False)):
        with torch_models(offline=outer), pytest.raises(RuntimeError, match="cannot nest"), torch_models(offline=inner):
            pass


def test_offline_errors_other_than_a_missing_file_are_not_disguised(
    monkeypatch: pytest.MonkeyPatch, cache: Path
) -> None:
    install_fake_torch(monkeypatch)
    install_fake_hugging_face(monkeypatch, cached={"model.yaml"})
    import huggingface_hub

    def corrupt(repo_id: str, filename: str, **kwargs: object) -> str:
        raise PermissionError("cache folder is read-only")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", corrupt)
    with torch_models(offline=True), pytest.raises(PermissionError):
        hf_download("adefossez/HTDemucs", "model.yaml")
