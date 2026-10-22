"""The phones over HTTPS: `woodshed app --cert --key` (a certificate made with mkcert, say)."""

from __future__ import annotations

import datetime
import http.client
import ipaddress
import json
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from tests.test_band import LAN, needs_lan
from woodshed import app, tls
from woodshed.errors import WoodshedError
from woodshed.run import Options


def make_certificate(
    folder: Path, ips: list[str], names: list[str], password: bytes | None = None
) -> tuple[Path, Path]:
    """A self-signed certificate for these addresses and names, as mkcert makes one (a test only)."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "woodshed test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    sans: list[x509.GeneralName] = [x509.IPAddress(ipaddress.ip_address(a)) for a in ips]
    sans += [x509.DNSName(n) for n in names]
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .sign(key, hashes.SHA256())
    )
    folder.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = folder / "cert.pem", folder / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    encryption: serialization.KeySerializationEncryption = (
        serialization.BestAvailableEncryption(password) if password else serialization.NoEncryption()
    )
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption))
    return cert_path, key_path


@pytest.fixture
def certificate(tmp_path: Path) -> tuple[Path, Path]:
    return make_certificate(tmp_path / "certs", ["127.0.0.1", *LAN[:1]], ["localhost", "woodshed.test"])


def trusting(cert: Path) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(cert))
    context.check_hostname = False  # the host is checked by the app itself (its Host rule), not by this client
    return context


def get(port: int, path: str, cert: Path, host: str, address: str = "127.0.0.1") -> tuple[int, bytes]:
    conn = http.client.HTTPSConnection(address, port, timeout=10, context=trusting(cert))
    conn.request("GET", path, headers={"Host": host})
    answer = conn.getresponse()
    body = answer.read()
    conn.close()
    return answer.status, body


def serving(srv: app.AppServer) -> app.AppServer:
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def network_server(
    tmp_path: Path, certificate: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> Iterator[app.AppServer]:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    library = app.Library(tmp_path / "library", Options(use_stems=False, open_page=False))
    srv = serving(app.AppServer(library, "0.0.0.0", 0, tls=tls.load(*certificate, library.root)))
    yield srv
    srv.shutdown()
    srv.server_close()


def test_on_the_network_the_library_answers_over_https(
    network_server: app.AppServer, certificate: tuple[Path, Path]
) -> None:
    port = network_server.port
    status, body = get(port, "/api/token", certificate[0], f"127.0.0.1:{port}")
    assert status == 200 and json.loads(body)["token"] == network_server.token
    assert network_server.url == f"https://localhost:{port}/"
    assert get(port, "/api/token", certificate[0], f"woodshed.test:{port}")[0] == 200  # a name in the certificate
    assert get(port, "/api/token", certificate[0], f"evil.example:{port}")[0] == 421  # still no other name
    assert app.running_here(port)  # started twice: the running one is found over HTTPS too


def test_the_live_stream_runs_over_https(network_server: app.AppServer, certificate: tuple[Path, Path]) -> None:
    port = network_server.port
    conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=10, context=trusting(certificate[0]))
    conn.request("GET", f"/api/live?t={network_server.token}", headers={"Host": f"127.0.0.1:{port}"})
    events = conn.getresponse()
    assert events.status == 200 and events.readline().startswith(b"data: ")
    conn.close()


def test_a_phone_that_does_not_trust_the_certificate_prints_no_traceback(
    network_server: app.AppServer, capfd: pytest.CaptureFixture[str]
) -> None:
    port = network_server.port
    for _ in range(3):
        refused = http.client.HTTPSConnection("127.0.0.1", port, timeout=5, context=ssl.create_default_context())
        with pytest.raises(ssl.SSLError):
            refused.request("GET", "/api/token")  # the default trust store does not know this certificate
        refused.close()
        plain = http.client.HTTPConnection("127.0.0.1", port, timeout=5)  # an old http:// bookmark
        with pytest.raises((OSError, http.client.HTTPException)):
            plain.request("GET", "/api/token")
            plain.getresponse().read()
        plain.close()
    err = capfd.readouterr().err
    assert "Traceback" not in err
    assert err.count("does not trust the certificate") == 1  # said once, not at every attempt


@needs_lan
def test_the_phones_door_is_https_and_the_computer_stays_http(
    tmp_path: Path, certificate: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WOODSHED_CACHE", str(tmp_path / "cache"))
    library = app.Library(tmp_path / "library", Options(use_stems=False, open_page=False))
    srv = serving(app.AppServer(library, "127.0.0.1", 0, tls=tls.load(*certificate, library.root)))
    monkeypatch.setattr(app, "lan_addresses", lambda: LAN[:1])
    try:
        assert srv.url == f"http://127.0.0.1:{srv.port}/"  # this computer: as before
        srv.set_door(True)
        assert srv.lan_urls() == [f"https://{LAN[0]}:{srv.port}/"]  # the addresses and the QR code
        status, _ = get(srv.port, "/api/songs", certificate[0], f"{LAN[0]}:{srv.port}", address=LAN[0])
        assert status == 200
        srv.set_door(False)
        with pytest.raises(OSError):
            get(srv.port, "/api/songs", certificate[0], f"{LAN[0]}:{srv.port}", address=LAN[0])
    finally:
        srv.shutdown()
        srv.server_close()


def test_wrong_certificate_files_are_said_before_the_library_starts(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    cert, key = make_certificate(tmp_path / "a", ["127.0.0.1"], ["localhost"])
    other_cert, other_key = make_certificate(tmp_path / "b", ["127.0.0.1"], ["localhost"])
    with pytest.raises(WoodshedError, match="no such file") as missing:
        tls.load(tmp_path / "nope.pem", key, library)
    assert "nope.pem" in str(missing.value)
    with pytest.raises(WoodshedError, match="do not go together"):
        tls.load(cert, other_key, library)
    _, locked = make_certificate(tmp_path / "c", ["127.0.0.1"], ["localhost"], password=b"secret")
    with pytest.raises(WoodshedError, match="protected by a password"):
        tls.load(tmp_path / "c" / "cert.pem", locked, library)  # never a prompt that hangs a container
    inside_cert, inside_key = make_certificate(library / "certs", ["127.0.0.1"], ["localhost"])
    with pytest.raises(WoodshedError, match="inside the library"):
        tls.load(inside_cert, inside_key, library)  # the library is served: the key would be too
    assert "PRIVATE KEY" not in str(missing.value)
    loaded = tls.load(other_cert, other_key, library)
    assert "localhost" in loaded.names and loaded.context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_the_command_takes_both_files_or_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from woodshed import cli

    seen: dict[str, object] = {}
    monkeypatch.setattr(app, "serve", lambda *a, **k: seen.update(k))
    cert, key = make_certificate(tmp_path / "certs", ["127.0.0.1"], ["localhost"])
    with pytest.raises(SystemExit):
        cli.main(["app", str(tmp_path / "lib"), "--no-open", "--cert", str(cert)])
    assert cli.main(["app", str(tmp_path / "lib"), "--no-open", "--cert", str(cert), "--key", str(key)]) == 0
    assert seen["tls"] == (cert, key)
    monkeypatch.setenv("WOODSHED_CERT", str(cert))
    monkeypatch.setenv("WOODSHED_KEY", str(key))
    seen.clear()
    assert cli.main(["app", str(tmp_path / "lib"), "--no-open"]) == 0  # the Docker image's way
    assert seen["tls"] == (cert, key)
