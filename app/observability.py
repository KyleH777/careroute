"""Request IDs, JSON logs, audit events and Prometheus metrics (ADR-0012).

- Every request gets an ID: a well-formed inbound `X-Request-ID` is kept,
  anything else is replaced with a uuid4. It's returned in the response
  header and attached to every log line written while handling the request.
- Each request writes exactly one JSON line to `careroute.access` (method,
  route template, path without the query string, status, duration). Query
  strings stay out of logs: they can carry identifiers.
- `audit()` writes `event=audit` lines to `careroute.audit`, so Log Analytics
  holds a copy of the audit trail that doesn't depend on the database.
- Metrics live in a private registry, served only by a separate listener on
  METRICS_PORT. The API port never serves /metrics, and on Azure ingress maps
  only the API port, so metrics aren't reachable from the public URL.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, MutableMapping
from datetime import UTC, datetime
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Histogram, start_http_server
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from starlette.routing import Match

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

access_log = logging.getLogger("careroute.access")
audit_log = logging.getLogger("careroute.audit")
error_log = logging.getLogger("careroute.error")


# --- logging -----------------------------------------------------------------

# Stamp the current request ID onto every record when it's created, so it
# survives however late the record is formatted (queued handlers, tests).
_base_factory = logging.getLogRecordFactory()


def _record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    record = _base_factory(*args, **kwargs)
    if not hasattr(record, "request_id"):
        record.request_id = request_id_var.get()
    return record


if getattr(logging.getLogRecordFactory(), "__name__", "") != "_record_factory":
    logging.setLogRecordFactory(_record_factory)


class JsonFormatter(logging.Formatter):
    """One JSON object per line; structured fields come via extra={"fields": ...}."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            entry["request_id"] = request_id
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Send the app's and uvicorn's logs to stderr as JSON. Idempotent."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    # careroute.access is the access log. uvicorn's would duplicate every
    # request and add the client IP, so it stays off even without
    # --no-access-log.
    logging.getLogger("uvicorn.access").disabled = True
    _configured = True


def audit(action: str, **fields: Any) -> None:
    """Record an audit event (who did what to which record). No free text."""
    audit_log.info(
        action, extra={"fields": {"event": "audit", "action": action, **fields}}
    )


# --- metrics -----------------------------------------------------------------

REGISTRY = CollectorRegistry()

REQUESTS = Counter(
    "careroute_http_requests",
    "HTTP requests by route template, method and status.",
    ["method", "route", "status"],
    registry=REGISTRY,
)
LATENCY = Histogram(
    "careroute_http_request_duration_seconds",
    "HTTP request latency by route template and method.",
    ["method", "route"],
    registry=REGISTRY,
)


class _PoolCollector(Collector):
    """SQLAlchemy connection-pool gauges, read at scrape time."""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        from app.db import engine  # late import: avoid a cycle at import time

        pool: Any = engine.pool
        for name, doc, read in (
            ("size", "Configured pool size.", "size"),
            ("checked_out", "Connections currently in use.", "checkedout"),
            ("overflow", "Connections beyond the pool size.", "overflow"),
        ):
            fn = getattr(pool, read, None)
            if fn is not None:
                yield GaugeMetricFamily(f"careroute_db_pool_{name}", doc, value=fn())


REGISTRY.register(_PoolCollector())

_metrics_started = False


def start_metrics_server() -> None:
    """Serve REGISTRY on METRICS_PORT, if set. Never on the API port."""
    global _metrics_started
    port = os.environ.get("METRICS_PORT")
    if not port or _metrics_started:
        return
    start_http_server(int(port), registry=REGISTRY)
    _metrics_started = True
    logging.getLogger("careroute").info("metrics listening on port %s", port)


# --- middleware --------------------------------------------------------------


def _route_template(app: Any, scope: Scope) -> str:
    for route in getattr(getattr(app, "router", None), "routes", []):
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return str(getattr(route, "path_format", getattr(route, "path", "")))
    return "unmatched"


class RequestContextMiddleware:
    """Pure ASGI: request ID, one access line, metrics, 500s with a request ID."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = next(
            (
                v.decode("latin-1")
                for k, v in scope.get("headers", [])
                if k.decode("latin-1").lower() == REQUEST_ID_HEADER.lower()
            ),
            "",
        )
        request_id = inbound if _VALID_REQUEST_ID.match(inbound) else str(uuid.uuid4())
        token = request_id_var.set(request_id)
        status_code = 500
        started = False
        start = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status_code, started
            if message["type"] == "http.response.start":
                started = True
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append(
                    (REQUEST_ID_HEADER.lower().encode(), request_id.encode())
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            status_code = 500
            error_log.exception("unhandled error")
            if not started:
                body = b'{"detail":"internal server error"}'
                await send_with_id(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
        finally:
            elapsed = time.perf_counter() - start
            route = _route_template(scope.get("app"), scope)
            method = scope.get("method", "")
            REQUESTS.labels(method, route, str(status_code)).inc()
            LATENCY.labels(method, route).observe(elapsed)
            access_log.info(
                "%s %s %s",
                method,
                scope.get("path", ""),
                status_code,
                extra={
                    "fields": {
                        "event": "request",
                        "method": method,
                        "route": route,
                        "path": scope.get("path", ""),
                        "status": status_code,
                        "duration_ms": round(elapsed * 1000, 2),
                    }
                },
            )
            request_id_var.reset(token)
