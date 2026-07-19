import json
import logging

import pytest
from starlette.requests import Request

from eventdrop.config import settings
from eventdrop.logging_config import JsonFormatter
from eventdrop.utils.client_ip import ClientIPMiddleware, get_client_ip


def make_record(name="eventdrop.test", msg="hello", args=None, **kwargs):
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=42,
        msg=msg,
        args=args,
        exc_info=kwargs.get("exc_info"),
    )


def make_request(headers=None, client=("10.0.0.1", 51234)):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
        "client": client,
    }
    return Request(scope)


# --- JsonFormatter -----------------------------------------------------------


def test_plain_record_is_single_json_line():
    out = JsonFormatter().format(make_record())
    assert "\n" not in out
    payload = json.loads(out)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "eventdrop.test"
    assert payload["msg"] == "hello"
    assert payload["line"] == 42
    # Timestamp is present and ISO-8601 with millisecond precision
    assert payload["ts"].count(":") >= 2
    assert "." in payload["ts"]


def test_access_record_yields_structured_fields():
    record = make_record(
        name="uvicorn.access",
        msg='%s - "%s %s HTTP/%s" %d',
        args=("203.0.113.7:0", "GET", "/events/?page=2", "1.1", 200),
    )
    payload = json.loads(JsonFormatter().format(record))

    assert payload["client_ip"] == "203.0.113.7"
    assert payload["method"] == "GET"
    assert payload["path"] == "/events/"
    assert payload["query"] == "page=2"
    assert payload["http_version"] == "1.1"
    assert payload["status"] == 200
    assert isinstance(payload["status"], int)


def test_access_record_without_query_string():
    record = make_record(
        name="uvicorn.access",
        msg='%s - "%s %s HTTP/%s" %d',
        args=("198.51.100.4:443", "POST", "/upload/abc", "1.1", 201),
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["path"] == "/upload/abc"
    assert payload["query"] == ""


def test_access_record_ipv6_client():
    record = make_record(
        name="uvicorn.access",
        msg='%s - "%s %s HTTP/%s" %d',
        args=("::1:8000", "GET", "/", "1.1", 200),
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["client_ip"] == "::1"


def test_unexpected_access_args_degrade_gracefully():
    """A future uvicorn changing the args shape must not raise inside the handler."""
    record = make_record(
        name="uvicorn.access", msg="%s %s %s", args=("GET", "/", "200")
    )
    payload = json.loads(JsonFormatter().format(record))
    assert "status" not in payload
    assert "path" not in payload
    assert payload["msg"] == "GET / 200"


def test_malformed_record_does_not_raise():
    """A msg/args mismatch must not propagate out of the formatter."""
    record = make_record(msg="one placeholder %s", args=("a", "b", "c"))
    payload = json.loads(JsonFormatter().format(record))
    assert "one placeholder" in payload["msg"]


def test_non_int_status_degrades_gracefully():
    record = make_record(
        name="uvicorn.access",
        msg='%s - "%s %s HTTP/%s" %s',
        args=("203.0.113.7:0", "GET", "/", "1.1", "not-a-status"),
    )
    payload = json.loads(JsonFormatter().format(record))
    assert "status" not in payload


def test_exception_stays_on_one_line():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = make_record(msg="failed", exc_info=sys.exc_info())

    out = JsonFormatter().format(record)
    assert "\n" not in out
    payload = json.loads(out)
    assert "ValueError: boom" in payload["exc"]
    assert "Traceback" in payload["exc"]


def test_extra_fields_are_merged():
    record = make_record()
    record.event_id = 7
    record.uploader = "someone@example.com"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["event_id"] == 7
    assert payload["uploader"] == "someone@example.com"


def test_non_serialisable_extra_does_not_raise():
    record = make_record()
    record.obj = object()
    payload = json.loads(JsonFormatter().format(record))
    assert isinstance(payload["obj"], str)


# --- get_client_ip -----------------------------------------------------------


def test_client_ip_uses_socket_peer_when_proxy_untrusted(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    request = make_request(headers={"X-Forwarded-For": "203.0.113.7"})
    # Header is present but must be ignored — it is spoofable.
    assert get_client_ip(request) == "10.0.0.1"


def test_client_ip_uses_forwarded_header_when_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = make_request(headers={"X-Forwarded-For": "203.0.113.7"})
    assert get_client_ip(request) == "203.0.113.7"


def test_client_ip_takes_leftmost_of_forwarded_chain(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = make_request(
        headers={"X-Forwarded-For": "203.0.113.7, 70.41.3.18, 150.172.238.178"}
    )
    assert get_client_ip(request) == "203.0.113.7"


def test_client_ip_falls_back_to_x_real_ip(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = make_request(headers={"X-Real-IP": "203.0.113.9"})
    assert get_client_ip(request) == "203.0.113.9"


def test_client_ip_falls_back_to_peer_when_no_headers(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    assert get_client_ip(make_request()) == "10.0.0.1"


@pytest.mark.parametrize("trusted", [True, False])
def test_client_ip_is_none_without_socket(monkeypatch, trusted):
    """httpx ASGITransport provides no client, so this must not raise."""
    monkeypatch.setattr(settings, "trust_proxy_headers", trusted)
    assert get_client_ip(make_request(client=None)) is None


def test_client_ip_ignores_empty_forwarded_header(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = make_request(headers={"X-Forwarded-For": "   "})
    assert get_client_ip(request) == "10.0.0.1"


# --- ClientIPMiddleware ------------------------------------------------------


async def call_middleware(scope, monkeypatch, trusted):
    monkeypatch.setattr(settings, "trust_proxy_headers", trusted)
    seen = {}

    async def downstream(inner_scope, receive, send):
        seen["client"] = inner_scope.get("client")

    await ClientIPMiddleware(downstream)(scope, None, None)
    return seen["client"]


async def test_middleware_rewrites_scope_client_when_trusted(monkeypatch):
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"203.0.113.7")],
        "client": ("172.18.0.5", 40000),
    }
    assert await call_middleware(scope, monkeypatch, trusted=True) == ("203.0.113.7", 0)
    # Mutated in place — this is what uvicorn's access logger reads at response time.
    assert scope["client"] == ("203.0.113.7", 0)


async def test_middleware_leaves_scope_alone_when_untrusted(monkeypatch):
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"203.0.113.7")],
        "client": ("172.18.0.5", 40000),
    }
    assert await call_middleware(scope, monkeypatch, trusted=False) == ("172.18.0.5", 40000)


async def test_middleware_ignores_lifespan_scope(monkeypatch):
    """Lifespan scopes have no headers key; touching them would raise."""
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    called = {}

    async def downstream(scope, receive, send):
        called["yes"] = True

    await ClientIPMiddleware(downstream)({"type": "lifespan"}, None, None)
    assert called["yes"]
