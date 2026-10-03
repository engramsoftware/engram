"""Tests for the SSRF-hardened fetch_url MCP tool (no real network: MockTransport + stub resolver)."""
import asyncio

import httpx
import pytest

from mcp_tools import web_fetch
from mcp_tools.web_fetch import MAX_BODY_BYTES, MAX_CHARS_LIMIT, UNTRUSTED_NOTE, fetch_url

PUBLIC_IP = "93.184.215.14"


def make_resolver(table: dict[str, list[str]] | None = None, default: list[str] | None = None):
    table = table or {}
    calls: list[tuple[str, int]] = []

    async def resolver(host: str, port: int) -> list[str]:
        calls.append((host, port))
        return table.get(host, default if default is not None else [PUBLIC_IP])

    resolver.calls = calls
    return resolver


class Recorder:
    """MockTransport handler that records requests and delegates to a route function."""

    def __init__(self, route=None):
        self.requests: list[httpx.Request] = []
        self.route = route or (lambda req: httpx.Response(200, text="ok", headers={"content-type": "text/plain"}))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.route(request)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_allow_private(monkeypatch):
    monkeypatch.delenv(web_fetch.ALLOW_PRIVATE_ENV, raising=False)


@pytest.mark.parametrize(
    "url, table",
    [
        ("http://127.0.0.1:8000/", {}),
        ("http://localhost/", {"localhost": ["127.0.0.1"]}),
        ("http://169.254.169.254/latest/meta-data/", {}),
        ("http://10.0.0.1/", {}),
        ("http://100.100.100.200/", {}),
        ("http://[::1]/", {}),
        ("http://[::ffff:127.0.0.1]/", {}),
        ("http://0.0.0.0/", {}),
        ("http://224.0.0.1/", {}),
        ("http://totally-public.example.com/", {"totally-public.example.com": ["192.168.1.5"]}),
        ("http://mixed.example.com/", {"mixed.example.com": [PUBLIC_IP, "10.1.2.3"]}),
        ("http://v6local.example.com/", {"v6local.example.com": ["fe80::1%eth0"]}),
        ("http://sixtofour.example.com/", {"sixtofour.example.com": ["2002:7f00:1::1"]}),
        ("file:///etc/passwd", {}),
        ("ftp://x", {}),
        ("http://user:pw@example.com/", {}),
        ("http://@example.com/", {}),
        ("http:///nohost", {}),
        ("javascript:alert(1)", {}),
        ("", {}),
    ],
)
def test_blocked_targets_never_hit_transport(url, table):
    rec = Recorder()
    with pytest.raises(ValueError):
        run(fetch_url(url, transport=rec.transport, resolver=make_resolver(table)))
    assert rec.requests == []


def test_public_fetch_returns_shape():
    rec = Recorder(lambda req: httpx.Response(200, text="hello world", headers={"content-type": "text/html; charset=utf-8"}))
    resolver = make_resolver()
    result = run(fetch_url("https://example.com/page", transport=rec.transport, resolver=resolver))
    assert result == {
        "url": "https://example.com/page",
        "final_url": "https://example.com/page",
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "truncated": False,
        "content": "hello world",
        "note": UNTRUSTED_NOTE,
    }
    assert resolver.calls == [("example.com", 443)]
    assert len(rec.requests) == 1


def test_redirect_to_loopback_is_blocked():
    def route(req):
        if req.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
        return httpx.Response(200, text="secret", headers={"content-type": "text/plain"})

    rec = Recorder(route)
    with pytest.raises(ValueError, match="127.0.0.1"):
        run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))
    assert [r.url.host for r in rec.requests] == ["example.com"]


def test_redirect_to_host_resolving_private_is_blocked():
    rec = Recorder(lambda req: httpx.Response(301, headers={"location": "https://internal.corp/"}))
    resolver = make_resolver({"internal.corp": ["172.16.0.9"]})
    with pytest.raises(ValueError):
        run(fetch_url("http://example.com/", transport=rec.transport, resolver=resolver))
    assert len(rec.requests) == 1


def test_redirect_to_file_scheme_is_blocked():
    rec = Recorder(lambda req: httpx.Response(302, headers={"location": "file:///etc/passwd"}))
    with pytest.raises(ValueError, match="scheme"):
        run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))


def test_public_redirect_reports_final_url():
    def route(req):
        if req.url.path == "/start":
            return httpx.Response(301, headers={"location": "/moved?x=1"})
        if req.url.path == "/moved":
            return httpx.Response(307, headers={"location": "https://other.example.org/final"})
        return httpx.Response(200, text="done", headers={"content-type": "text/plain"})

    rec = Recorder(route)
    result = run(fetch_url("http://example.com/start", transport=rec.transport, resolver=make_resolver()))
    assert result["final_url"] == "https://other.example.org/final"
    assert result["url"] == "http://example.com/start"
    assert result["content"] == "done"
    assert [str(r.url) for r in rec.requests] == [
        "http://example.com/start",
        "http://example.com/moved?x=1",
        "https://other.example.org/final",
    ]


def _chain_route(length: int):
    def route(req):
        n = int(req.url.path.strip("/") or 0)
        if n < length:
            return httpx.Response(302, headers={"location": f"/{n + 1}"})
        return httpx.Response(200, text=f"end {n}", headers={"content-type": "text/plain"})

    return route


def test_five_redirects_allowed():
    rec = Recorder(_chain_route(5))
    result = run(fetch_url("http://example.com/0", transport=rec.transport, resolver=make_resolver()))
    assert result["content"] == "end 5"
    assert len(rec.requests) == 6


def test_six_redirects_raise():
    rec = Recorder(_chain_route(6))
    with pytest.raises(ValueError, match="redirect"):
        run(fetch_url("http://example.com/0", transport=rec.transport, resolver=make_resolver()))
    assert len(rec.requests) == 6


def test_large_body_is_capped_and_truncated():
    body = b"a" * (5 * 1024 * 1024)
    read_sizes = []

    def route(req):
        async def stream():
            for i in range(0, len(body), 64 * 1024):
                read_sizes.append(64 * 1024)
                yield body[i:i + 64 * 1024]

        return httpx.Response(200, content=stream(), headers={"content-type": "text/plain"})

    rec = Recorder(route)
    result = run(fetch_url("http://example.com/big", max_chars=10**9, transport=rec.transport, resolver=make_resolver()))
    assert result["truncated"] is True
    assert len(result["content"]) <= MAX_CHARS_LIMIT
    assert len(result["content"]) == MAX_CHARS_LIMIT  # 10**9 clamped to the limit
    # Streaming stopped at the byte cap instead of reading all 5 MB.
    assert sum(read_sizes) <= MAX_BODY_BYTES + 64 * 1024


def test_body_byte_cap_sets_truncated_even_under_max_chars(monkeypatch):
    monkeypatch.setattr(web_fetch, "MAX_BODY_BYTES", 100)
    rec = Recorder(lambda req: httpx.Response(200, text="b" * 500, headers={"content-type": "text/plain"}))
    result = run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))
    assert result["truncated"] is True
    assert result["content"] == "b" * 100


def test_max_chars_truncates():
    rec = Recorder(lambda req: httpx.Response(200, text="x" * 50, headers={"content-type": "text/plain"}))
    result = run(fetch_url("http://example.com/", max_chars=10, transport=rec.transport, resolver=make_resolver()))
    assert result == {**result, "content": "x" * 10, "truncated": True}
    result = run(fetch_url("http://example.com/", max_chars=0, transport=rec.transport, resolver=make_resolver()))
    assert result["content"] == "x"


@pytest.mark.parametrize("given, expected", [(10**6, 30.0), (0, 1.0), (-5, 1.0), (7, 7.0), (float("nan"), 15.0)])
def test_timeout_clamped_and_client_hardened(monkeypatch, given, expected):
    recorded = {}
    real_client = httpx.AsyncClient

    class RecordingClient(real_client):
        def __init__(self, *args, **kwargs):
            recorded.update(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(web_fetch.httpx, "AsyncClient", RecordingClient)
    rec = Recorder()
    run(fetch_url("http://example.com/", timeout_sec=given, transport=rec.transport, resolver=make_resolver()))
    assert recorded["timeout"] == httpx.Timeout(expected)
    assert recorded["follow_redirects"] is False
    assert recorded["trust_env"] is False


def test_image_content_type_rejected():
    rec = Recorder(lambda req: httpx.Response(200, content=b"\x89PNG\r\n", headers={"content-type": "image/png"}))
    with pytest.raises(ValueError, match="image/png"):
        run(fetch_url("http://example.com/x.png", transport=rec.transport, resolver=make_resolver()))


def test_missing_content_type_rejected():
    rec = Recorder(lambda req: httpx.Response(200, content=b"data"))
    with pytest.raises(ValueError):
        run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))


@pytest.mark.parametrize("ctype", ["application/ld+json", "application/rss+xml", "application/xml", "text/csv"])
def test_structured_text_types_allowed(ctype):
    rec = Recorder(lambda req: httpx.Response(200, text="<x/>", headers={"content-type": ctype}))
    result = run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))
    assert result["content"] == "<x/>"


def test_404_raises_runtime_error():
    rec = Recorder(lambda req: httpx.Response(404, text="nope", headers={"content-type": "text/html"}))
    with pytest.raises(RuntimeError, match="HTTP 404 from http://example.com/missing"):
        run(fetch_url("http://example.com/missing", transport=rec.transport, resolver=make_resolver()))


def test_network_error_raises_runtime_error():
    def route(req):
        raise httpx.ConnectError("connection refused", request=req)

    with pytest.raises(RuntimeError, match="connection refused"):
        run(fetch_url("http://example.com/", transport=Recorder(route).transport, resolver=make_resolver()))


def test_dns_failure_raises_runtime_error():
    async def resolver(host, port):
        raise OSError("Name or service not known")

    rec = Recorder()
    with pytest.raises(RuntimeError, match="resolve"):
        run(fetch_url("http://nxdomain.example/", transport=rec.transport, resolver=resolver))
    assert rec.requests == []


def test_json_body_returned_as_text():
    rec = Recorder(lambda req: httpx.Response(200, json={"a": [1, 2]}))
    result = run(fetch_url("http://api.example.com/v1", transport=rec.transport, resolver=make_resolver()))
    assert isinstance(result["content"], str)
    assert result["content"].replace(" ", "") == '{"a":[1,2]}'
    assert result["content_type"].startswith("application/json")
    assert result["note"] == UNTRUSTED_NOTE


def test_decodes_with_response_charset_and_replaces_errors():
    rec = Recorder(lambda req: httpx.Response(200, content="café".encode("latin-1"), headers={"content-type": "text/plain; charset=iso-8859-1"}))
    assert run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))["content"] == "café"
    rec = Recorder(lambda req: httpx.Response(200, content=b"ok\xff", headers={"content-type": "text/plain"}))
    assert run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))["content"] == "ok�"


def test_allow_private_env_permits_loopback(monkeypatch):
    monkeypatch.setenv(web_fetch.ALLOW_PRIVATE_ENV, "1")
    rec = Recorder(lambda req: httpx.Response(200, text="local", headers={"content-type": "text/plain"}))
    result = run(fetch_url("http://127.0.0.1:8000/", transport=rec.transport, resolver=make_resolver()))
    assert result["content"] == "local"
    assert len(rec.requests) == 1
    # Scheme/credential checks still apply with the escape hatch on.
    with pytest.raises(ValueError):
        run(fetch_url("file:///etc/passwd", transport=rec.transport, resolver=make_resolver()))


def test_default_resolver_blocks_localhost():
    # localhost resolves via /etc/hosts, so this exercises the real getaddrinfo path offline.
    rec = Recorder()
    with pytest.raises(ValueError, match="non-public"):
        run(fetch_url("http://localhost:9/", transport=rec.transport))
    assert rec.requests == []


# --- Regression tests from adversarial review ---------------------------------------------


@pytest.mark.parametrize("host", ["2130706433", "0x7f.1", "0x7f000001", "0177.0.0.1", "127.1", "0xa9.254.169.254"])
def test_legacy_numeric_ipv4_hosts_blocked_without_trusting_resolver(host):
    # getaddrinfo maps these to loopback/metadata; a resolver that disagrees must not matter.
    # (httpx itself rejects dotted forms with leading zeros; the rest reach the IP check.)
    rec = Recorder()
    resolver = make_resolver(default=[PUBLIC_IP])
    with pytest.raises(ValueError, match="non-public|Invalid IPv4"):
        run(fetch_url(f"http://{host}/", transport=rec.transport, resolver=resolver))
    assert rec.requests == [] and resolver.calls == []


def test_idn_host_is_checked_in_the_form_httpx_connects_to():
    # IDNA 2003 maps faß -> fass, IDNA 2008 (what httpx uses) -> xn--fa-hia. Vetting the
    # wrong one would let an attacker point the other at a private address.
    rec = Recorder()
    resolver = make_resolver({"faß.example": [PUBLIC_IP], "fass.example": [PUBLIC_IP],
                              "xn--fa-hia.example": ["10.0.0.7"]})
    with pytest.raises(ValueError, match="non-public"):
        run(fetch_url("http://faß.example/", transport=rec.transport, resolver=resolver))
    assert rec.requests == []
    assert resolver.calls == [("xn--fa-hia.example", 80)]


def test_resolved_host_matches_requested_host():
    rec = Recorder()
    resolver = make_resolver()
    run(fetch_url("http://Straße.Example./p", transport=rec.transport, resolver=resolver))
    assert [h for h, _ in resolver.calls] == [rec.requests[0].url.raw_host.decode()]


@pytest.mark.parametrize("addr", ["64:ff9b::a00:1", "64:ff9b::a9fe:a9fe", "::7f00:1", "::ffff:0:7f00:1", "fec0::1", "100::1"])
def test_ipv6_forms_python_calls_global_are_blocked(addr):
    rec = Recorder()
    with pytest.raises(ValueError):
        run(fetch_url(f"http://[{addr}]/", transport=rec.transport, resolver=make_resolver()))
    with pytest.raises(ValueError):
        run(fetch_url("http://v6.example.com/", transport=rec.transport, resolver=make_resolver({"v6.example.com": [addr]})))
    assert rec.requests == []


def test_nat64_wrapping_public_ipv4_is_allowed():
    rec = Recorder()
    result = run(fetch_url("http://dns64.example.com/", transport=rec.transport,
                           resolver=make_resolver({"dns64.example.com": ["64:ff9b::5db8:d70e", "2606:2800:21f:cb07::1"]})))
    assert result["content"] == "ok"


@pytest.mark.parametrize("headers", [{}, {"location": ""}, {"location": "   "}])
def test_redirect_without_location_raises(headers):
    rec = Recorder(lambda req: httpx.Response(302, text="moved", headers={"content-type": "text/html", **headers}))
    with pytest.raises(RuntimeError, match="without a Location"):
        run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))


@pytest.mark.parametrize("location", ["http:127.0.0.1", "http://example.org\t/"])
def test_malformed_redirect_location_raises_runtime_error(location):
    rec = Recorder(lambda req: httpx.Response(302, headers={"location": location}))
    with pytest.raises(RuntimeError):
        run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))
    assert len(rec.requests) == 1


def test_scheme_relative_redirects():
    def route(req):
        if req.url.host == "example.com":
            return httpx.Response(302, headers={"location": "//other.example.org/p#frag"})
        return httpx.Response(200, text="there", headers={"content-type": "text/plain"})

    rec = Recorder(route)
    result = run(fetch_url("https://example.com/", transport=rec.transport, resolver=make_resolver()))
    assert result["final_url"] == "https://other.example.org/p"

    rec = Recorder(lambda req: httpx.Response(302, headers={"location": "//127.0.0.1/admin"}))
    with pytest.raises(ValueError, match="127.0.0.1"):
        run(fetch_url("https://example.com/", transport=rec.transport, resolver=make_resolver()))
    assert len(rec.requests) == 1


def _streamed(data: bytes, encoding: str, chunk: int = 64 * 1024):
    async def stream():
        for i in range(0, len(data), chunk):
            yield data[i:i + chunk]

    return lambda req: httpx.Response(200, content=stream(),
                                      headers={"content-type": "text/plain", "content-encoding": encoding})


def test_gzip_bomb_is_capped_without_inflating_everything():
    import gzip
    import tracemalloc

    bomb = gzip.compress(b"\0" * (50 * 1024 * 1024))  # ~50 KB on the wire
    rec = Recorder(_streamed(bomb, "gzip"))
    tracemalloc.start()
    try:
        result = run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result["truncated"] is True
    assert peak < 20 * 1024 * 1024  # was ~130 MB when httpx inflated the chunk in full


def test_compressed_bodies_decode():
    import gzip
    import zlib

    text = "hello " * 1000
    rec = Recorder(_streamed(gzip.compress(text.encode()), "gzip", chunk=100))
    result = run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))
    assert result["content"] == text and result["truncated"] is False
    rec = Recorder(_streamed(zlib.compress(text.encode()), "deflate"))
    assert run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))["content"] == text


@pytest.mark.parametrize("encoding, body", [("br", b"\x1b\x00"), ("gzip", b"not gzip at all")])
def test_unsupported_or_corrupt_encoding_raises_runtime_error(encoding, body):
    rec = Recorder(_streamed(body, encoding))
    with pytest.raises(RuntimeError):
        run(fetch_url("http://example.com/", transport=rec.transport, resolver=make_resolver()))


def test_numeric_argument_edge_cases():
    rec = Recorder(lambda req: httpx.Response(200, text="x" * 50, headers={"content-type": "text/plain"}))
    res = make_resolver()
    # JSON parsers accept Infinity; it must clamp, not raise OverflowError.
    assert run(fetch_url("http://example.com/", max_chars=float("inf"), transport=rec.transport, resolver=res))["content"] == "x" * 50
    assert run(fetch_url("http://example.com/", max_chars=float("-inf"), transport=rec.transport, resolver=res))["content"] == "x"
    for bad in [{"max_chars": None}, {"max_chars": "lots"}, {"max_chars": float("nan")}, {"timeout_sec": None}]:
        with pytest.raises(ValueError):
            run(fetch_url("http://example.com/", transport=rec.transport, resolver=res, **bad))
    assert web_fetch._clamp_timeout(float("inf")) == web_fetch.MAX_TIMEOUT_SEC


@pytest.mark.parametrize("url", ["http://example.com:0/", "http://example.com:99999/", "http://example.com:abc/",
                                 "http://example.com\\@127.0.0.1/", "http://[::1/"])
def test_bad_ports_and_malformed_authorities_rejected(url):
    rec = Recorder()
    with pytest.raises(ValueError):
        run(fetch_url(url, transport=rec.transport, resolver=make_resolver()))
    assert rec.requests == []
