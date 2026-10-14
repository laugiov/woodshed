"""`woodshed app`: a home page for a library of songs, and an upload that runs the processing.

A small HTTP server on this computer (standard library only). The song pages are the same as the
command line makes; the app lists them, serves them, and turns uploaded files into new pages.

Security: the server answers any page the browser opens, so it trusts nothing it did not give
out itself. It binds 127.0.0.1 by default, refuses a Host header that is not its own (DNS
rebinding), needs a per-run token in a custom header for every upload (a cross-site form or
fetch cannot send it, and preflights are refused), and never reads or writes outside the library.
"""

from __future__ import annotations

import json
import mimetypes
import queue
import re
import secrets
import shutil
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from woodshed import audio
from woodshed.errors import WoodshedError
from woodshed.run import MANIFEST, Options, Reporter, first_pass, second_pass

MAX_UPLOAD = 2 * 1024**3  # 2 GB: a long video
FREE_MARGIN = 2 * 1024**3  # room left for the page's tracks after an upload
CHUNK = 1024 * 1024
TOKEN_HEADER = "X-Woodshed-Token"
TYPES = {
    ".flac": "audio/flac",
    ".woff2": "font/woff2",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".mid": "audio/midi",
    ".musicxml": "application/vnd.recordare.musicxml+xml",
    ".cho": "text/plain; charset=utf-8",
    ".lab": "text/plain; charset=utf-8",
}


@dataclass
class Job:
    id: str
    name: str
    status: str = "queued"  # queued, analysing, separating, done, failed
    step: str = ""
    percent: int = 0
    message: str = ""
    page: str | None = None  # the page folder, as soon as a first page exists
    started: float = field(default_factory=time.time)


class JobReporter(Reporter):
    """Progress of one job, kept for the home page instead of printed."""

    def __init__(self, job: Job) -> None:
        super().__init__()
        self.job = job

    def say(self, text: str) -> None:
        self.job.message = text.strip()

    def progress(self, step: str, fraction: float) -> None:
        self.job.step = step

    def stems(self, fraction: float) -> None:
        self.job.status = "separating"
        self.job.percent = int(fraction * 100)


class Library:
    """A folder of songs: uploads in `songs/`, one page folder per song next to it."""

    def __init__(self, root: Path, opts: Options) -> None:
        self.root = root.expanduser().resolve()
        self.songs = self.root / "songs"
        self.songs.mkdir(parents=True, exist_ok=True)
        self.opts = opts
        self.jobs: dict[str, Job] = {}
        self.reserved: set[str] = set()
        for leftover in self.songs.glob(".*.part"):  # uploads cut short by a stop or a crash
            leftover.unlink(missing_ok=True)
        self.queue: queue.Queue[tuple[Job, Path, Options]] = queue.Queue()
        self.lock = threading.Lock()
        threading.Thread(target=self._work, name="woodshed-jobs", daemon=True).start()

    def pages(self) -> list[dict[str, Any]]:
        out = []
        for manifest in sorted(self.root.glob(f"*.woodshed/{MANIFEST}")):
            if manifest.parent.is_symlink():  # served pages are real folders of the library
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                info = dict(data["summary"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            info["complete"] = data.get("complete") is True
            info["folder"] = manifest.parent.name  # the real folder, never a name read from a file
            out.append(info)
        return sorted(out, key=lambda s: str(s.get("title", "")).lower())

    def state(self) -> dict[str, Any]:
        with self.lock:
            # Finished jobs stay visible a while (a failure for an hour), then are forgotten.
            now = time.time()
            for key in [
                k
                for k, j in self.jobs.items()
                if now - j.started > (3600 if j.status == "failed" else 60) and j.status in ("done", "failed")
            ]:
                del self.jobs[key]
            jobs = [asdict(j) for j in self.jobs.values()]
        return {"songs": self.pages(), "jobs": jobs}

    def reserve(self, name: str) -> Path:
        """Where an upload goes: a safe name, unique by its stem (one page per stem), reserved
        until the upload ends so two uploads of one name never share a file."""
        clean = re.sub(r'[<>:"/\\|?*#%\x00-\x1f]', "_", Path(name).name).strip(" .")
        stem, suffix = Path(clean).stem or "song", Path(clean).suffix.lower()
        if suffix not in audio.MEDIA:
            raise WoodshedError(f"{name}: not an audio or video file")
        with self.lock:
            taken = {p.stem.lower() for p in self.songs.iterdir() if not p.name.startswith(".")} | self.reserved
            candidate, n = stem, 1
            while candidate.lower() in taken:
                n += 1
                candidate = f"{stem} ({n})"
            self.reserved.add(candidate.lower())
        return self.songs / f"{candidate}{suffix}"

    def release(self, path: Path) -> None:
        with self.lock:
            self.reserved.discard(path.stem.lower())

    def add(self, path: Path, opts: Options) -> Job:
        job = Job(secrets.token_hex(6), path.name)
        with self.lock:
            self.jobs[job.id] = job
        self.queue.put((job, path, opts))
        return job

    def _work(self) -> None:
        while True:
            job, path, opts = self.queue.get()
            report = JobReporter(job)
            try:
                job.status = "analysing"
                done = first_pass(path, opts, report, self.root)
                job.page = done.page.name
                if done.stems_to_come:
                    job.status = "separating"
                    done = second_pass(done, report)
                job.status, job.message = "done", "Ready"
            except (WoodshedError, OSError) as exc:
                job.status, job.message = "failed", str(exc)
                if job.page is None:  # nothing came of it: the file does not keep its name taken
                    path.unlink(missing_ok=True)
            except Exception as exc:  # a bug must not stop the queue
                job.status, job.message = "failed", f"unexpected error: {exc}"
                traceback.print_exc()
            finally:
                self.queue.task_done()


def home_html(token: str) -> str:
    page = resources.files("woodshed").joinpath("page").joinpath("home.html").read_text(encoding="utf-8")
    return page.replace("{{TOKEN}}", token)


class Handler(BaseHTTPRequestHandler):
    server: AppServer
    protocol_version = "HTTP/1.1"
    timeout = 30  # seconds without a byte from the client: a stalled upload frees its thread

    def log_message(self, format: str, *args: Any) -> None:  # quiet: progress is on the page
        pass

    # Checks shared by every request.

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.server.hosts

    def _send(self, status: int, body: bytes, kind: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def _error(self, status: int, message: str) -> None:
        # The request body may be unread: the connection must end, or the rest of the body would be
        # read as the next request.
        self.close_connection = True
        self._send(status, json.dumps({"error": message}).encode(), "application/json", {"Connection": "close"})

    # Routes.

    def do_OPTIONS(self) -> None:
        self._error(HTTPStatus.METHOD_NOT_ALLOWED, "cross-origin requests are not accepted")

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self._host_ok():
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "unknown host")
            return
        path = unquote(urlsplit(self.path).path)
        if "\x00" in path:
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        if path in ("/", "/index.html"):
            self._send(
                HTTPStatus.OK,
                home_html(self.server.token).encode(),
                TYPES[".html"],
                {"Content-Security-Policy": HOME_CSP},
            )
        elif path == "/api/songs":
            self._json(HTTPStatus.OK, self.server.library.state())
        elif path.startswith("/app/"):
            self._static(self.server.assets, path[len("/app/") :])
        else:
            self._static(self.server.library.root, path.lstrip("/"))

    def do_POST(self) -> None:
        if not self._host_ok():
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "unknown host")
            return
        given = self.headers.get(TOKEN_HEADER, "").encode("utf-8", "surrogateescape")
        if not secrets.compare_digest(given, self.server.token.encode()):
            self._error(HTTPStatus.FORBIDDEN, "missing or wrong token")
            return
        url = urlsplit(self.path)
        if url.path != "/api/songs":
            self._error(HTTPStatus.NOT_FOUND, "no such endpoint")
            return
        query = parse_qs(url.query)
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            self._error(HTTPStatus.LENGTH_REQUIRED, "send the file with a Content-Length")
            return
        declared = self.headers.get("Content-Length", "")
        length = int(declared) if declared.isdigit() and len(declared) < 16 else -1
        if not 0 < length <= MAX_UPLOAD:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "a song file must be between 1 byte and 2 GB")
            return
        if shutil.disk_usage(self.server.library.root).free < length + FREE_MARGIN:
            self._error(HTTPStatus.INSUFFICIENT_STORAGE, "not enough free disk space for this file and its tracks")
            return
        try:
            opts = self._options(query)
            target = self.server.library.reserve(query.get("name", [""])[0])
        except (WoodshedError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        partial = target.with_name(f".{target.name}.{secrets.token_hex(4)}.part")
        try:
            with partial.open("wb") as out:
                left = length
                while left:
                    chunk = self.rfile.read(min(CHUNK, left))
                    if not chunk:
                        raise OSError("the upload stopped early")
                    out.write(chunk)
                    left -= len(chunk)
            partial.replace(target)
        except (OSError, TimeoutError) as exc:  # a client that stops sending times out here
            partial.unlink(missing_ok=True)
            self.server.library.release(target)
            self._error(HTTPStatus.BAD_REQUEST, f"the upload did not complete ({exc})")
            return
        self.server.library.release(target)
        job = self.server.library.add(target, opts)
        self._json(HTTPStatus.ACCEPTED, asdict(job))

    def _options(self, query: dict[str, list[str]]) -> Options:
        def one(key: str) -> str | None:
            values = query.get(key)
            return values[0] if values and values[0] else None

        beats = int(one("beats_per_bar") or 4)
        tempo = one("bpm")
        bpm = float(tempo) if tempo else None
        if not 2 <= beats <= 12 or (bpm is not None and not 30 <= bpm <= 300):
            raise ValueError("beats per bar 2 to 12, tempo 30 to 300 BPM")
        base = self.server.library.opts
        return Options(
            use_stems=base.use_stems, offline=base.offline, open_page=False,
            beats_per_bar=beats, sevenths=one("sevenths") == "1", bpm=bpm,
        )  # fmt: skip

    def _static(self, root: Path, rel: str) -> None:
        target = (root / rel).resolve()
        if target.is_dir() and not self.path.split("?")[0].endswith("/") and target.is_relative_to(root):
            # Relative links in a page need its folder URL to end with a slash.
            self._send(HTTPStatus.MOVED_PERMANENTLY, b"", "text/plain", {"Location": urlsplit(self.path).path + "/"})
            return
        if target.is_dir():
            target = target / "index.html"
        hidden = any(part.startswith(".") for part in Path(rel).parts)
        if hidden or not target.is_relative_to(root) or not target.is_file():
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        kind = TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        size = target.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        wanted = re.fullmatch(r"bytes=(\d{0,15})-(\d{0,15})", self.headers.get("Range", ""))
        if wanted and size and any(wanted.groups()):  # "bytes=-" and malformed ranges: the whole file
            # Audio seeking needs ranges: the browser asks for the part it plays from.
            a, b = wanted.groups()
            if a:
                start, end = int(a), min(int(b), size - 1) if b else size - 1
            elif b:
                start = max(0, size - int(b))
            if start >= size:  # starts after the end of the file
                self._send(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, b"", kind, {"Content-Range": f"bytes */{size}"})
                return
            if start > end:  # an inverted range is ignored: the whole file
                start, end = 0, size - 1
            else:
                status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with target.open("rb") as f:
            f.seek(start)
            left = length
            while left:
                chunk = f.read(min(CHUNK, left))
                if not chunk:  # the file shrank while being sent: this answer is short, end the connection
                    self.close_connection = True
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):  # the browser stopped reading
                    self.close_connection = True
                    return
                left -= len(chunk)


HOME_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, library: Library, host: str = "127.0.0.1", port: int = 0) -> None:
        super().__init__((host, port), Handler)
        self.library = library
        self.token = secrets.token_urlsafe(24)
        with resources.as_file(resources.files("woodshed").joinpath("page")) as page:
            self.assets = Path(page).resolve()
        bound = self.server_address[1]
        self.port = int(bound)
        names = {"127.0.0.1", "localhost", "[::1]"} | ({host} if host not in ("0.0.0.0", "::") else set())
        self.hosts = {f"{name}:{self.port}" for name in names}

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"


LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def serve(root: Path, opts: Options, host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True) -> None:
    import webbrowser

    if host not in LOOPBACK:
        # The token stops other web sites, not other computers: anyone who can reach the port can
        # read the home page and its token. Only for a container whose port is published on
        # 127.0.0.1 (docker run -p 127.0.0.1:8000:8000).
        print(
            f"woodshed app: listening on {host}: every computer that can reach this port can use the library",
            flush=True,
        )

    library = Library(root, opts)
    server = AppServer(library, host, port)
    print(f"woodshed app: {server.url}  (library: {library.root}; Ctrl-C to stop)", flush=True)
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        shutil.rmtree(library.songs / ".tmp", ignore_errors=True)
