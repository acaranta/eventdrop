"""Client IP resolution behind a reverse proxy.

When EVENTDROP_TRUST_PROXY_HEADERS is enabled, the connecting peer is assumed to be a
trusted reverse proxy and the originating client is read from X-Forwarded-For (or
X-Real-IP). When it is disabled, only the real socket peer is used, so a client cannot
spoof its own logged address.
"""

from eventdrop.config import settings


def _forwarded_ip(headers) -> str | None:
    """Extract the originating client IP from proxy headers, if present.

    `headers` may be a Starlette Headers object or any case-insensitive mapping
    exposing .get().
    """
    forwarded_for = headers.get("x-forwarded-for")
    if forwarded_for:
        # Left-most entry is the original client; the rest are intermediate proxies.
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first

    real_ip = headers.get("x-real-ip")
    if real_ip:
        real_ip = real_ip.strip()
        if real_ip:
            return real_ip

    return None


def get_client_ip(request) -> str | None:
    """Return the best-known client IP for a request, or None if unavailable.

    Returns None under test transports (httpx ASGITransport), which have no socket and
    therefore no request.client.
    """
    if settings.trust_proxy_headers:
        forwarded = _forwarded_ip(request.headers)
        if forwarded:
            return forwarded

    client = request.client
    return client.host if client else None


class ClientIPMiddleware:
    """Rewrite scope["client"] from proxy headers so downstream consumers see the
    real client.

    Implemented as pure ASGI rather than BaseHTTPMiddleware because uvicorn emits its
    access log at response time by reading the very same scope dict this mutates
    (see uvicorn.protocols.http.h11_impl). Mutating it in place is what makes the
    access log report the originating client rather than the proxy.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and settings.trust_proxy_headers:
            host = self._forwarded_host(scope)
            if host:
                # The originating port is not recoverable from proxy headers.
                scope["client"] = (host, 0)
        return await self.app(scope, receive, send)

    @staticmethod
    def _forwarded_host(scope) -> str | None:
        headers = {}
        for raw_name, raw_value in scope.get("headers", []):
            name = raw_name.decode("latin1").lower()
            if name in ("x-forwarded-for", "x-real-ip") and name not in headers:
                headers[name] = raw_value.decode("latin1")
        return _forwarded_ip(headers) if headers else None
