"""HTTPS for the band's phones: a certificate and its key given to `woodshed app` (made with mkcert, say).

Over plain HTTP on the band's Wi-Fi a phone has no Screen Wake Lock: its browser keeps that for secure pages.
The files are checked before the library starts, and their content is never printed.
"""

from __future__ import annotations

import ssl
import sys
from dataclasses import dataclass, field
from pathlib import Path

from woodshed.errors import WoodshedError


@dataclass(frozen=True)
class Tls:
    context: ssl.SSLContext
    names: frozenset[str] = field(default_factory=frozenset)  # the DNS names of the certificate: accepted as Host


def _refuse_password() -> str:
    raise WoodshedError("the key is protected by a password: give woodshed a key without one (mkcert makes those)")


def load(cert: Path, key: Path, library: Path) -> Tls:
    """The server context for these files, or a WoodshedError saying what is wrong with which file."""
    root = library.expanduser().resolve()
    for path in (cert, key):
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise WoodshedError(f"{path}: no such file" if not resolved.exists() else f"{path}: not a file")
        if resolved.is_relative_to(root):  # the library is served: the key would be downloadable
            raise WoodshedError(f"{path} is inside the library, which is served to the phones: keep it elsewhere")
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_cert_chain(cert.expanduser(), key.expanduser(), password=_refuse_password)
    except WoodshedError:
        raise
    except PermissionError as exc:
        raise WoodshedError(
            f"{exc.filename or key}: cannot be read by this user (in Docker: chmod 640 it, or set WOODSHED_UID"
            " to its owner)"
        ) from None
    except ssl.SSLError as exc:
        if "BAD_DECRYPT" in str(exc) or "bad decrypt" in str(exc).lower():
            raise WoodshedError("the key is protected by a password: give woodshed a key without one") from None
        raise WoodshedError(f"{cert} and {key} do not go together, or are not a certificate and its key") from None
    return Tls(context, frozenset(_dns_names(cert.expanduser())))


def _dns_names(cert: Path) -> list[str]:
    """The DNS names the certificate is for (its subject alternative names). The standard library decodes a
    certificate file only through this test helper; without it, the address literals still work."""
    try:
        decoded = ssl._ssl._test_decode_cert(str(cert))  # type: ignore[attr-defined]
    except (AttributeError, ssl.SSLError, OSError, ValueError):
        print(
            "woodshed app: could not read the certificate's names: the phones must type its IP address",
            file=sys.stderr,
            flush=True,
        )
        return []
    names = [value.lower() for kind, value in decoded.get("subjectAltName", ()) if kind == "DNS"]
    return [n for n in names if "*" not in n]  # a wildcard is no name a Host header carries
