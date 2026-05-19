"""Request-scoped trace context middleware."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from opentelemetry import trace, context as otel_context
from opentelemetry.propagate import extract


class TracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        carrier = dict(request.headers)
        ctx = extract(carrier)
        tracer = trace.get_tracer("supply-chain-agent")

        with tracer.start_as_current_span(
            f"{request.method} {request.url.path}",
            context=ctx,
            kind=trace.SpanKind.SERVER,
        ) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.route", request.url.path)

            trace_id = format(span.get_span_context().trace_id, "032x")
            request.state.trace_id = trace_id

            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            return response
