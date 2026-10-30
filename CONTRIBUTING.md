# Contributing to woodshed

Thanks for wanting to help. Musicians and developers are both welcome: a clear report of a chart
that went wrong is as useful as a pull request.

## Reporting a problem with a song

Open an issue with the bug template. Say what you expected (the chord you hear, the bar where the
section starts) and what woodshed showed, with `woodshed --version`, your OS and browser.

**Never attach or link a recording you don't have the rights to share**, and no full lyrics. Describe
the song instead (tempo, key, style), or reproduce the problem on a song under a free licence, such
as the demo song in [`demo/`](demo/LICENSE.md).

## Setting up

You need [uv](https://docs.astral.sh/uv/). ffmpeg is only needed for AAC (M4A) and video files: MP3,
WAV, FLAC and Ogg are read without it.
The singer's key (the recording in another key) renders with ffmpeg's Rubber Band filter (Ubuntu's
and Debian's ffmpeg have it; Homebrew's plain `ffmpeg` does not), else with the Rubber Band program,
3.2 or newer, from woodshed's tools folder (`WOODSHED_TOOLS` moves it) or the PATH: `sudo apt install
rubberband-cli` on Ubuntu 24.04, or the installers' `get_rubberband` (macOS) / `Get-Rubberband` (Windows).
Without them their tests are skipped; `WOODSHED_REQUIRE_PITCH=1` (the filter) and
`WOODSHED_REQUIRE_RUBBERBAND=1` (the program) make them fail instead, as the CI does.

```bash
git clone https://github.com/laugiov/woodshed && cd woodshed
uv sync --extra stems                    # Python, PyTorch (CPU), Demucs, beat_this
uv run playwright install chromium firefox
uv run playwright install --with-deps webkit   # optional: the tablet tests (it may need sudo for system libraries)
uv run woodshed path/to/song.mp3        # try it
```

`uv sync` without `--extra stems` is enough for most of the code (chords, structure, the page) and
much lighter.

## Before a pull request

```bash
uv run pytest -n auto  # Python and page tests (Playwright)
scripts/ci.sh          # a few minutes: hygiene, lint, types, tests, the page in Chromium
scripts/ci.sh --full   # what GitHub runs: every Python, Firefox, the stems extra, the package
```

`pre-commit install` runs the quick checks on each commit.

The rules the checks enforce, and the ones they can't:

- **No audio, no video, nothing from `private/`** is ever committed (`scripts/check_repo.py`), apart
  from the demo song in `demo/`, under a free licence and pinned by hash. Tests build their songs
  with the synthesiser in `tests/`.
- **The page works offline**: no CDN, no fetch to the internet. Vendored files are pinned by hash.
- **Every change comes with tests**, the page included: Playwright tests run in Chromium and Firefox.
- **English** in code, comments, docs and messages. The page itself speaks English and French: a
  text it shows goes through `W.t("...")` with its French in `core/i18n-fr.js` (a test checks it),
  and the song's own text (title, chords, words) is marked `translate="no"`.
- **The page draws with tokens only**: colours, fonts, radii and shadows come from the custom
  properties at the top of `assets/app.css`, so every skin reaches a new feature without being
  touched. A new need is a new token with a default derived from the others; `tests/test_skins.py`
  and `tests/page/test_skin_sweeps.py` fail on a literal colour, radius or font. Making a skin:
  [docs/skins.md](docs/skins.md).
- **Audio quality is never traded for speed**: no mono, no lossy re-encoding, no truncated notes.
- Python 3.10 to 3.14, typed (`mypy --strict`), formatted with `ruff`.

Security problems go through [private reporting](SECURITY.md), never a public issue.

## Pull requests

Keep a pull request to one change, say why in the description, and include a screenshot when the
page changes. For every change a user notices, add a line under **Unreleased** in
[`CHANGELOG.md`](CHANGELOG.md), in a musician's words: what you can do now, or what got fixed. Pull requests are squash-merged; the CI checks must pass first.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be kind; we're all here to
play music.
