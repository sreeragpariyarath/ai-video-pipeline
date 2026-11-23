from __future__ import annotations

import ipaddress
import socket
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urlunparse

import requests
import urllib3
from requests.adapters import HTTPAdapter

from .evidence_schemas import ExtractionConfig, FetchedPage
from .source_discovery import canonicalize_url


CONNECT_TIMEOUT_SECONDS = 5.0
USER_AGENT = "AIVideoFactoryResearchBot/1.0 (evidence extraction)"
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_TRANSIENT_STATUS = {500, 502, 503, 504}
_ALLOWED_MIME = {"text/html", "application/xhtml+xml", "text/plain"}
_CHUNK_BYTES = 65_536


class FetchError(RuntimeError):
    """Fetch failed permanently: unsafe URL, bad response, or protocol error."""


class TransientFetchError(FetchError):
    """Fetch failed temporarily (timeout, connection, 5xx); safe to retry."""


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _check_safe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        _check_safe_ip(mapped)
        return
    if (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise FetchError("URL resolves to a non-public address.")


def _resolve_safe_ip(host: str, port: int | None, scheme: str) -> str:
    """Resolve the host and require every returned address to be public."""
    if _is_ip_literal(host):
        _check_safe_ip(ipaddress.ip_address(host))
        return host
    service = port if port is not None else (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, service, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise FetchError(f"DNS resolution failed for host: {host}") from None
    if not infos:
        raise FetchError(f"DNS resolution failed for host: {host}")
    addresses: list[str] = []
    for info in infos:
        raw = info[4][0].split("%")[0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            raise FetchError(f"DNS returned an invalid address for host: {host}") from None
        _check_safe_ip(ip)
        addresses.append(str(ip))
    return addresses[0]


def _validate_and_pin(url: str) -> tuple[str, str | None]:
    """Return a URL pinned to a validated IP plus the original Host header.

    The connection target becomes the validated IP so a second DNS lookup
    cannot redirect the request (DNS rebinding / TOCTOU). The original
    hostname is preserved for the Host header, TLS SNI, and certificate
    verification via _PinningAdapter.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise FetchError("URL must not target localhost.")
    ip = _resolve_safe_ip(host, parsed.port, parsed.scheme)
    if _is_ip_literal(host):
        return url, None
    netloc = f"[{ip}]" if ":" in ip else ip
    host_header = host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
        host_header = f"{host}:{parsed.port}"
    pinned = urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, "")
    )
    return pinned, host_header


class _PinningAdapter(HTTPAdapter):
    """Keep TLS SNI and certificate checks on the original hostname.

    The request URL points at the validated IP; without this adapter the
    certificate would be checked against the IP and SNI would be lost.
    assert_hostname is part of the urllib3 pool key, so each hostname gets
    its own pool even when several hostnames share one IP.
    """

    def send(self, request, **kwargs):  # type: ignore[override]
        host = request.headers.get("Host", "")
        if host.startswith("["):
            hostname = host[1 : host.find("]")]
        else:
            hostname = host.split(":")[0]
        if (
            request.url.startswith("https://")
            and hostname
            and not _is_ip_literal(hostname)
        ):
            self.poolmanager.connection_pool_kw["assert_hostname"] = hostname
            conn = self.get_connection_with_tls_context(
                request,
                kwargs.get("verify", True),
                proxies=kwargs.get("proxies"),
                cert=kwargs.get("cert"),
            )
            conn.conn_kw["server_hostname"] = hostname
        else:
            self.poolmanager.connection_pool_kw.pop("assert_hostname", None)
        return super().send(request, **kwargs)


class PageFetcher(ABC):
    def fetch(self, url: str) -> FetchedPage:
        try:
            canonical = canonicalize_url(url)
        except ValueError as exc:
            raise FetchError(f"Invalid URL: {exc}") from None
        return self._fetch(canonical)

    @abstractmethod
    def _fetch(self, url: str) -> FetchedPage:
        """Fetch a canonicalized URL; raise FetchError on failure."""

    def close(self) -> None:
        """Release resources; the base fetcher holds none."""

    def __enter__(self) -> PageFetcher:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class HttpPageFetcher(PageFetcher):
    def __init__(self, config: ExtractionConfig | None = None):
        # The pinning adapter relies on urllib3 2.x pool-key and SNI behavior.
        if int(urllib3.__version__.split(".")[0]) != 2:
            raise FetchError(
                "HttpPageFetcher requires urllib3 2.x for IP pinning; "
                "run `pip install -r requirements.txt`."
            )
        self._config = config or ExtractionConfig()
        self._session = requests.Session()
        # Ambient proxies/credentials must not reroute untrusted fetches:
        # proxy pools would bypass the per-hostname pool separation.
        self._session.trust_env = False
        adapter = _PinningAdapter()
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def close(self) -> None:
        self._session.close()

    def _fetch(self, url: str) -> FetchedPage:
        # Unrelated sources must not share cookie state.
        self._session.cookies.clear()
        deadline = time.monotonic() + self._config.max_fetch_seconds
        last_message = "Fetch failed."
        for attempt in range(self._config.max_retries + 1):
            if time.monotonic() >= deadline:
                raise TransientFetchError("Fetch deadline exceeded.") from None
            try:
                return self._fetch_chain(url, deadline)
            except TransientFetchError as exc:
                last_message = str(exc)
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as exc:
                last_message = f"Fetch failed: {type(exc).__name__}"
            except requests.exceptions.RequestException as exc:
                # Suppress chaining: raw exceptions may embed response details.
                raise FetchError(f"Fetch failed: {type(exc).__name__}") from None
            if attempt < self._config.max_retries:
                if time.monotonic() >= deadline:
                    raise TransientFetchError("Fetch deadline exceeded.") from None
                time.sleep(2**attempt)
        raise TransientFetchError(last_message) from None

    def _fetch_chain(self, url: str, deadline: float) -> FetchedPage:
        current = url
        redirects = 0
        for _ in range(self._config.max_redirects + 1):
            if time.monotonic() >= deadline:
                raise TransientFetchError("Fetch deadline exceeded.")
            pinned, host_header = _validate_and_pin(current)
            headers = {"User-Agent": USER_AGENT}
            if host_header is not None:
                headers["Host"] = host_header
            response = self._session.get(
                pinned,
                headers=headers,
                allow_redirects=False,
                stream=True,
                timeout=(CONNECT_TIMEOUT_SECONDS, self._config.timeout_seconds),
            )
            try:
                if response.status_code in _REDIRECT_CODES:
                    current = self._redirect_target(current, response)
                    redirects += 1
                    continue
                return self._read_response(response, url, current, redirects, deadline)
            finally:
                response.close()
        raise FetchError("Too many redirects.")

    def _redirect_target(self, current: str, response) -> str:
        location = response.headers.get("Location")
        if not location or not location.strip():
            raise FetchError("Redirect response without a Location header.")
        target = urljoin(current, location.strip())
        try:
            target = canonicalize_url(target)
        except ValueError:
            raise FetchError("Redirect target is not a valid http(s) URL.") from None
        if urlparse(current).scheme == "https" and urlparse(target).scheme == "http":
            raise FetchError("HTTPS-to-HTTP downgrade redirect rejected.")
        return target

    def _read_response(
        self, response, requested_url: str, final_url: str, redirects: int, deadline: float
    ) -> FetchedPage:
        status = response.status_code
        if status in _TRANSIENT_STATUS:
            raise TransientFetchError(f"Fetch failed: HTTP {status}.")
        if not 200 <= status < 300:
            raise FetchError(f"Fetch failed: HTTP {status}.")
        content_type = response.headers.get("Content-Type") or ""
        mime = content_type.split(";")[0].strip().lower()
        if mime not in _ALLOWED_MIME:
            raise FetchError("Unsupported content type; only HTML and plain text allowed.")
        # iter_content yields decoded bytes, so the cap also stops
        # decompression bombs, not just large raw transfers.
        body = bytearray()
        truncated = False
        for chunk in response.iter_content(chunk_size=_CHUNK_BYTES):
            if time.monotonic() >= deadline:
                raise TransientFetchError("Fetch deadline exceeded.")
            body.extend(chunk)
            if len(body) > self._config.max_response_bytes:
                del body[self._config.max_response_bytes :]
                truncated = True
                break
        # requests assigns ISO-8859-1 to text/* without a charset (legacy RFC
        # default); only an explicitly declared charset may override UTF-8.
        encoding = "utf-8"
        for part in content_type.split(";")[1:]:
            key, _, value = part.strip().partition("=")
            if key.lower() == "charset" and value.strip():
                encoding = value.strip().strip('"')
        try:
            html = bytes(body).decode(encoding, errors="replace")
        except LookupError:
            html = bytes(body).decode("utf-8", errors="replace")
        return FetchedPage(
            requested_url=requested_url,
            final_url=final_url,
            status_code=status,
            content_type=mime,
            fetched_at=datetime.now(timezone.utc),
            html=html,
            truncated=truncated,
            redirect_count=redirects,
        )


_DEFAULT_MOCK_HTML = (
    "<html><head><title>Mock Article</title></head><body><article>"
    "<h1>Mock Article</h1>"
    "<p>Streaming prices rose 12 percent in 2026 according to the mock report. "
    "Households now pay more for streaming than for basic cable in many markets.</p>"
    "<p>The mock bureau published these figures on 2026-06-15.</p>"
    "</article></body></html>"
)


class MockPageFetcher(PageFetcher):
    """Deterministic offline fetcher. Values may be HTML or exceptions to raise."""

    def __init__(self, pages: dict[str, str | Exception] | None = None):
        self._pages: dict[str, str | Exception] = {}
        for key, value in (pages or {}).items():
            self._pages[canonicalize_url(key)] = value
        self.calls: list[str] = []

    def _fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        page = self._pages.get(url, _DEFAULT_MOCK_HTML)
        if isinstance(page, Exception):
            raise page
        return FetchedPage(
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            fetched_at=datetime.now(timezone.utc),
            html=page,
            truncated=False,
            redirect_count=0,
        )