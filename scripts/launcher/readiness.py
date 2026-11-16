"""Verify local services before announcing startup and opening the browser."""

from __future__ import annotations

import http.client
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from .model import LauncherError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class Readiness:
    """Probe frontend and CSRF endpoints, opening the frontend once both are ready.

    HTTPS uses the supplied PEM as a trust anchor while retaining certificate and
    hostname validation. Probe requests ignore proxy environment variables and
    redirects and never persist cookies from the CSRF response.
    """

    def __init__(
        self, frontend_url: str, backend_url: str, certificate_file: Path | None = None,
    ) -> None:
        self.frontend_url = frontend_url
        self._frontend_probe = self._endpoint(frontend_url, "/")
        self._backend_probe = self._endpoint(backend_url, "/api/v1/auth/csrf/")
        try:
            context = ssl.create_default_context(
                cafile=str(certificate_file) if certificate_file is not None else None,
            )
            if certificate_file is not None:
                # The supplied identity may end at a leaf or intermediate, without a root CA.
                context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        except (OSError, ssl.SSLError) as error:
            raise LauncherError(
                "readiness certificate could not be loaded; supply a readable PEM certificate file"
            ) from error
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=context),
            _NoRedirect(),
        )
        self._ready = False

    @staticmethod
    def _endpoint(url: str, path: str) -> str:
        try:
            parts = urllib.parse.urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
                raise ValueError("invalid service URL")
            parts.port
        except ValueError as error:
            raise LauncherError("readiness requires valid HTTP or HTTPS service URLs without credentials") from error
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))

    def __call__(self) -> bool:
        if self._ready:
            return True
        if not self._probe(self._frontend_probe) or not self._probe(self._backend_probe, csrf=True):
            return False
        self._ready = True
        print(f"[ready] Services are ready: {self.frontend_url}", flush=True)
        try:
            webbrowser.open(self.frontend_url)
        except (OSError, webbrowser.Error):
            print(f"Open the application in your browser: {self.frontend_url}", flush=True)
        return True

    def _probe(self, url: str, *, csrf: bool = False) -> bool:
        try:
            with self._opener.open(url, timeout=1.0) as response:
                if response.status != 200:
                    return False
                if not csrf:
                    return True
                # Bound parsing work even if another service occupies the port.
                body = response.read(65537)
                if len(body) > 65536:
                    return False
                payload = json.loads(body)
                return isinstance(payload, dict) and payload.get("success") is True
        except urllib.error.HTTPError as error:
            error.close()
            return False
        except (OSError, urllib.error.URLError, http.client.HTTPException,
                json.JSONDecodeError, UnicodeDecodeError):
            return False
