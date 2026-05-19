from __future__ import annotations

import hashlib

from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

# Free-text attributes that may carry PII — redacted before export.
# When adding a new free-text attribute, add it here in the same PR (§6.4).
REDACT_ATTRS: frozenset[str] = frozenset({
    "user.name",
    "user.email",
    "vendor.contact",
    "http.request.header.authorization",
    "enduser.id",
    "rag.query",  # may contain vendor names / user-supplied text
})


class PIIRedactionProcessor(SpanProcessor):
    """Redacts PII from span attributes before export.

    Hashes values rather than dropping them so audit trails remain intact.
    Raw values never reach the exporter.
    """

    def on_start(self, span, parent_context=None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        for attr in REDACT_ATTRS:
            if attr in (span.attributes or {}):
                raw = str(span.attributes[attr])
                span._attributes[attr] = "redacted:" + hashlib.sha256(raw.encode()).hexdigest()[:12]

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True
