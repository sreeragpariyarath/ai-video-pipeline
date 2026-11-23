import ipaddress
import socket
from types import SimpleNamespace

import pytest
import requests

from orchestrator.evidence_schemas import ExtractionConfig
from orchestrator.page_fetcher import (
    CONNECT_TIMEOUT_SECONDS,
    USER_AGENT,
    FetchError,
    HttpPageFetcher,
    MockPageFetcher,
    TransientFetchError,
)


PUBLIC_IP = "93.184.216.34"


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b"<html><body><p>ok</p></body></html>", encoding="utf-8", on_chunk=None):
        self.status_code = status
        self.headers = headers if headers is not None else {"Content-Type": "text/html"}
        self._body = body
        self.encoding = encoding
        self.closed = False
        self.history = []
        self.raw = SimpleNamespace(_original_response=None)
        self.url = ""
        self.is_redirect = False
        self.is_permanent_redirect = False
        self.links = {}
        self.next = None
        self._on_chunk = on_chunk

    def iter_content(self, chunk_size):
        for start in range(0, len(self._body), chunk_size):
            if self._on_chunk is not None:
                self._on_chunk()
            yield self._body[start : start + chunk_size]

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """Offline resolver: literal forms resolve locally, names use a mapping."""
    state = SimpleNamespace(calls=[], mapping={})

    def fake_getaddrinfo(host, port, *args, **kwargs):
        state.calls.append((host, port))
        if host in state.mapping:
            value = state.mapping[host]
            if isinstance(value, Exception):
                raise value
            ips = value
        else:
            try:
                ips = [str(ipaddress.ip_address(host))]
            except ValueError:
                try:
                    ips = [socket.inet_ntoa(socket.inet_aton(host))]
                except OSError:
                    ips = [PUBLIC_IP]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 443)) for ip in ips]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return state


@pytest.fixture(autouse=True)
def http(monkeypatch):
    state = SimpleNamespace(responses=[], requests=[], kwargs=[], on_send=None)

    def fake_send(self, request, **kwargs):
        state.requests.append(request)
        state.kwargs.append(kwargs)
        if state.on_send is not None:
            state.on_send()
        if not state.responses:
            return FakeResponse()
        item = state.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    return state


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr("orchestrator.page_fetcher.time.sleep", recorded.append)
    return recorded


def make_fetcher(**config) -> HttpPageFetcher:
    return HttpPageFetcher(ExtractionConfig(**config) if config else None)


def test_valid_http_url_pins_ip_and_preserves_host(http, dns):
    page = make_fetcher().fetch("http://example.com/article")
    assert page.status_code == 200
    assert page.final_url == "http://example.com/article"
    request = http.requests[0]
    assert request.url == f"http://{PUBLIC_IP}/article"
    assert request.headers["Host"] == "example.com"
    assert request.headers["User-Agent"] == USER_AGENT
    assert dns.calls == [("example.com", 80)]
    assert http.kwargs[0]["stream"] is True
    assert http.kwargs[0]["timeout"] == (CONNECT_TIMEOUT_SECONDS, 15.0)


def test_valid_https_url_keeps_sni_and_cert_hostname(http):
    fetcher = make_fetcher()
    fetcher.fetch("https://example.com/article")
    request = http.requests[0]
    assert request.url == f"https://{PUBLIC_IP}/article"
    assert request.headers["Host"] == "example.com"
    adapter = fetcher._session.get_adapter("https://example.com")
    assert adapter.poolmanager.connection_pool_kw["assert_hostname"] == "example.com"
    pool = adapter.get_connection_with_tls_context(http.requests[0], True)
    assert pool.host == PUBLIC_IP
    assert pool.conn_kw["server_hostname"] == "example.com"


def test_public_ip_literal_skips_dns(http, dns):
    make_fetcher().fetch(f"https://{PUBLIC_IP}/x")
    assert dns.calls == []
    assert http.requests[0].url == f"https://{PUBLIC_IP}/x"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/a",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "gopher://example.com/",
        "not a url",
        "",
    ],
)
def test_invalid_schemes_and_malformed_urls(url):
    with pytest.raises(FetchError):
        make_fetcher().fetch(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://sub.localhost/admin",
        "http://LOCALHOST./admin",
    ],
)
def test_localhost_rejected_before_dns(url, dns):
    with pytest.raises(FetchError, match="localhost"):
        make_fetcher().fetch(url)
    assert dns.calls == []


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.1",
        "2130706433",
        "0x7f000001",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.1.1",
        "240.0.0.1",
        "224.0.0.1",
        "0.0.0.0",
        "[::1]",
        "[fc00::1]",
        "[fe80::1]",
        "[ff02::1]",
        "[::]",
        "[::ffff:127.0.0.1]",
        "[::ffff:10.0.0.1]",
    ],
)
def test_unsafe_ip_literals_rejected(host, http):
    with pytest.raises(FetchError):
        make_fetcher().fetch(f"http://{host}/x")
    assert http.requests == []


def test_dns_returning_private_address_rejected(dns, http):
    dns.mapping["evil.example"] = ["127.0.0.1"]
    with pytest.raises(FetchError, match="non-public"):
        make_fetcher().fetch("https://evil.example/x")
    assert http.requests == []


def test_dns_mixed_public_and_private_rejected(dns):
    dns.mapping["mixed.example"] = [PUBLIC_IP, "10.0.0.1"]
    with pytest.raises(FetchError, match="non-public"):
        make_fetcher().fetch("https://mixed.example/x")


def test_dns_failure_fails_closed(dns):
    dns.mapping["down.example"] = socket.gaierror("name resolution failed")
    with pytest.raises(FetchError, match="DNS resolution failed"):
        make_fetcher().fetch("https://down.example/x")


def test_encoded_hostname_fails_closed(dns):
    dns.mapping["example%2ecom"] = socket.gaierror("bad host")
    with pytest.raises(FetchError):
        make_fetcher().fetch("https://example%2ecom/x")


def test_redirect_validated_and_followed(http, dns):
    http.responses.extend(
        [
            FakeResponse(status=302, headers={"Location": "https://other.example/final"}),
            FakeResponse(),
        ]
    )
    page = make_fetcher().fetch("https://example.com/start")
    assert page.final_url == "https://other.example/final"
    assert page.redirect_count == 1
    assert [host for host, _ in dns.calls] == ["example.com", "other.example"]
    assert http.requests[1].headers["Host"] == "other.example"


def test_relative_redirect_resolved(http):
    http.responses.extend(
        [
            FakeResponse(status=302, headers={"Location": "/next"}),
            FakeResponse(),
        ]
    )
    page = make_fetcher().fetch("https://example.com/start")
    assert page.final_url == "https://example.com/next"


def test_redirect_to_unsafe_target_rejected(http):
    http.responses.append(
        FakeResponse(status=302, headers={"Location": "http://127.0.0.1/admin"})
    )
    with pytest.raises(FetchError):
        make_fetcher().fetch("https://example.com/start")
    assert len(http.requests) == 1


def test_redirect_limit_enforced(http, sleeps):
    http.responses.extend(
        FakeResponse(status=302, headers={"Location": f"https://example.com/{i}"})
        for i in range(10)
    )
    with pytest.raises(FetchError, match="Too many redirects"):
        make_fetcher(max_redirects=2).fetch("https://example.com/start")
    assert len(http.requests) == 3


def test_https_downgrade_redirect_rejected(http):
    http.responses.append(
        FakeResponse(status=302, headers={"Location": "http://example.com/insecure"})
    )
    with pytest.raises(FetchError, match="downgrade"):
        make_fetcher().fetch("https://example.com/start")


def test_redirect_without_location_rejected(http):
    http.responses.append(FakeResponse(status=302, headers={}))
    with pytest.raises(FetchError, match="Location"):
        make_fetcher().fetch("https://example.com/start")


def test_timeout_retries_then_transient_error(http, sleeps):
    http.responses.extend(requests.exceptions.Timeout("timed out") for _ in range(3))
    with pytest.raises(TransientFetchError) as excinfo:
        make_fetcher().fetch("https://example.com/x")
    assert len(http.requests) == 3
    assert sleeps == [1, 2]
    assert excinfo.value.__cause__ is None
    assert "timed out" not in str(excinfo.value)


def test_connection_failure_retries(http, sleeps):
    http.responses.extend(
        requests.exceptions.ConnectionError("secret-token-xyz refused") for _ in range(3)
    )
    with pytest.raises(TransientFetchError) as excinfo:
        make_fetcher().fetch("https://example.com/x")
    assert "secret-token-xyz" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_transient_http_error_retried(http, sleeps):
    http.responses.extend([FakeResponse(status=503), FakeResponse()])
    page = make_fetcher().fetch("https://example.com/x")
    assert page.status_code == 200
    assert sleeps == [1]


def test_permanent_http_error_not_retried(http, sleeps):
    http.responses.append(FakeResponse(status=404))
    with pytest.raises(FetchError, match="HTTP 404"):
        make_fetcher().fetch("https://example.com/x")
    assert len(http.requests) == 1
    assert sleeps == []


def test_unsupported_mime_rejected(http):
    http.responses.append(
        FakeResponse(headers={"Content-Type": "application/pdf"})
    )
    with pytest.raises(FetchError, match="content type"):
        make_fetcher().fetch("https://example.com/x")


def test_missing_mime_rejected(http):
    http.responses.append(FakeResponse(headers={}))
    with pytest.raises(FetchError, match="content type"):
        make_fetcher().fetch("https://example.com/x")


def test_plain_text_allowed(http):
    http.responses.append(
        FakeResponse(headers={"Content-Type": "text/plain; charset=utf-8"}, body=b"hello")
    )
    page = make_fetcher().fetch("https://example.com/x")
    assert page.html == "hello"
    assert page.content_type == "text/plain"


def test_response_size_limit_truncates(http):
    http.responses.append(FakeResponse(body=b"a" * 500))
    page = make_fetcher(max_response_bytes=100).fetch("https://example.com/x")
    assert page.truncated is True
    assert len(page.html) == 100


def test_decoded_size_limit_truncates_bomb(http):
    # iter_content yields decoded bytes; a small transfer encoding a huge
    # body must still be capped on the decoded size.
    http.responses.append(
        FakeResponse(
            headers={"Content-Type": "text/html", "Content-Length": "10"},
            body=b"b" * 10_000,
        )
    )
    page = make_fetcher(max_response_bytes=200).fetch("https://example.com/x")
    assert page.truncated is True
    assert len(page.html) == 200


def test_under_limit_not_truncated(http):
    page = make_fetcher().fetch("https://example.com/x")
    assert page.truncated is False


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:0/x",
        "https://example.com:65536/x",
        "https:///path",
        "https://exa mple.com/x",
    ],
)
def test_malformed_urls_rejected(url):
    with pytest.raises(FetchError):
        make_fetcher().fetch(url)


def test_retry_configuration_respected(http, sleeps):
    http.responses.extend(requests.exceptions.Timeout() for _ in range(4))
    with pytest.raises(TransientFetchError):
        make_fetcher(max_retries=3).fetch("https://example.com/x")
    assert len(http.requests) == 4
    assert sleeps == [1, 2, 4]


def test_zero_retries_single_attempt(http, sleeps):
    http.responses.append(requests.exceptions.Timeout())
    with pytest.raises(TransientFetchError):
        make_fetcher(max_retries=0).fetch("https://example.com/x")
    assert len(http.requests) == 1
    assert sleeps == []


def test_non_retryable_request_exception_sanitized(http):
    http.responses.append(requests.exceptions.InvalidURL("secret-detail"))
    with pytest.raises(FetchError) as excinfo:
        make_fetcher().fetch("https://example.com/x")
    assert "secret-detail" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert len(http.requests) == 1


def test_responses_closed(http):
    response = FakeResponse()
    http.responses.append(response)
    make_fetcher().fetch("https://example.com/x")
    assert response.closed is True


def test_mock_fetcher_deterministic_and_offline():
    fetcher = MockPageFetcher({"https://example.com/a": "<html><body>hi</body></html>"})
    first = fetcher.fetch("https://example.com/a")
    second = fetcher.fetch("https://example.com/a")
    assert first.html == second.html == "<html><body>hi</body></html>"
    assert fetcher.calls == ["https://example.com/a"] * 2
    default = fetcher.fetch("https://other.example/b")
    assert "Mock Article" in default.html


def test_mock_fetcher_exception_injection():
    fetcher = MockPageFetcher({"https://example.com/a": FetchError("mock failure")})
    with pytest.raises(FetchError, match="mock failure"):
        fetcher.fetch("https://example.com/a")


def test_mock_fetcher_validates_urls():
    with pytest.raises(FetchError):
        MockPageFetcher().fetch("not a url")


@pytest.fixture
def fake_clock(monkeypatch):
    state = SimpleNamespace(now=1000.0, step=0.0)

    def tick():
        value = state.now
        state.now += state.step
        return value

    monkeypatch.setattr("orchestrator.page_fetcher.time.monotonic", tick)

    def fake_sleep(seconds):
        state.now += seconds

    monkeypatch.setattr("orchestrator.page_fetcher.time.sleep", fake_sleep)
    return state


def test_normal_request_within_deadline(fake_clock, http):
    page = make_fetcher(max_fetch_seconds=30).fetch("https://example.com/x")
    assert page.status_code == 200


def test_deadline_exceeded_before_request(fake_clock, http):
    fake_clock.step = 1.0  # clock advances past the budget between checks
    with pytest.raises(TransientFetchError, match="deadline"):
        make_fetcher(max_fetch_seconds=0.5).fetch("https://example.com/x")
    assert http.requests == []


def test_deadline_during_streaming_cleans_up(fake_clock, http):
    def slow_chunk():
        fake_clock.now += 40

    response = FakeResponse(body=b"a" * 200_000, on_chunk=slow_chunk)
    http.responses.append(response)
    with pytest.raises(TransientFetchError, match="deadline"):
        make_fetcher(max_fetch_seconds=30, max_retries=0).fetch("https://example.com/x")
    assert response.closed is True
    assert len(http.requests) == 1


def test_deadline_during_retry_stops_retrying(fake_clock, http):
    http.responses.extend(requests.exceptions.Timeout() for _ in range(5))
    with pytest.raises(TransientFetchError, match="deadline"):
        make_fetcher(max_fetch_seconds=2, max_retries=5).fetch("https://example.com/x")
    # attempt at t=0, sleep 1 -> t=1, attempt, sleep would reach t=3 > 2: stop
    assert len(http.requests) == 2


def test_deadline_during_redirect_chain(fake_clock, http):
    def slow_hop():
        fake_clock.now += 20

    http.on_send = slow_hop
    http.responses.extend(
        FakeResponse(status=302, headers={"Location": f"https://example.com/{i}"})
        for i in range(5)
    )
    with pytest.raises(TransientFetchError, match="deadline"):
        make_fetcher(max_fetch_seconds=30, max_retries=0).fetch("https://example.com/start")
    assert len(http.requests) == 2


def test_no_retry_sleep_after_deadline(fake_clock, http):
    http.responses.append(requests.exceptions.Timeout())

    def expire_during_attempt():
        fake_clock.now += 31

    http.on_send = expire_during_attempt
    with pytest.raises(TransientFetchError, match="deadline"):
        make_fetcher(max_fetch_seconds=30, max_retries=3).fetch("https://example.com/x")
    assert len(http.requests) == 1


def test_trust_env_disabled(http, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    fetcher = make_fetcher()
    assert fetcher._session.trust_env is False
    fetcher.fetch("https://example.com/x")
    assert http.requests[0].url == f"https://{PUBLIC_IP}/x"
    assert http.kwargs[0]["proxies"] == {}


def test_tls_verification_still_required(http):
    fetcher = make_fetcher()
    fetcher.fetch("https://example.com/x")
    assert http.kwargs[0]["verify"] is True
    adapter = fetcher._session.get_adapter("https://example.com")
    pool = adapter.get_connection_with_tls_context(http.requests[0], True)
    assert pool.cert_reqs == "CERT_REQUIRED"


def test_utf8_without_charset_declaration(http):
    body = "<html><body><p>Prices rose — café naïve 中文.</p></body></html>".encode("utf-8")
    http.responses.append(FakeResponse(body=body))
    page = make_fetcher().fetch("https://example.com/x")
    assert "café naïve 中文" in page.html


def test_explicit_utf8_charset(http):
    body = "héllo wörld".encode("utf-8")
    http.responses.append(
        FakeResponse(headers={"Content-Type": "text/html; charset=utf-8"}, body=body)
    )
    page = make_fetcher().fetch("https://example.com/x")
    assert page.html == "héllo wörld"


def test_explicit_non_utf8_charset(http):
    body = "héllo wörld".encode("iso-8859-1")
    http.responses.append(
        FakeResponse(headers={"Content-Type": "text/html; charset=iso-8859-1"}, body=body)
    )
    page = make_fetcher().fetch("https://example.com/x")
    assert page.html == "héllo wörld"


def test_invalid_charset_falls_back_to_utf8(http):
    body = "héllo".encode("utf-8")
    http.responses.append(
        FakeResponse(headers={"Content-Type": "text/html; charset=bogus-charset"}, body=body)
    )
    page = make_fetcher().fetch("https://example.com/x")
    assert page.html == "héllo"


def test_explicit_close_releases_session():
    fetcher = make_fetcher()
    adapter = fetcher._session.get_adapter("https://example.com")
    fetcher.fetch("https://example.com/x")
    fetcher.close()
    assert len(adapter.poolmanager.pools) == 0


def test_context_manager_closes_session(http):
    with make_fetcher() as fetcher:
        fetcher.fetch("https://example.com/x")
        adapter = fetcher._session.get_adapter("https://example.com")
    assert len(adapter.poolmanager.pools) == 0


def test_response_closed_on_http_error(http):
    response = FakeResponse(status=404)
    http.responses.append(response)
    with pytest.raises(FetchError):
        make_fetcher().fetch("https://example.com/x")
    assert response.closed is True


def test_cookies_do_not_persist_between_fetches(http):
    fetcher = make_fetcher()
    fetcher._session.cookies.set("session", "abc", domain="example.com", path="/")
    fetcher.fetch("https://example.com/x")
    assert len(fetcher._session.cookies) == 0


def test_urllib3_version_compatible():
    import urllib3

    assert int(urllib3.__version__.split(".")[0]) == 2