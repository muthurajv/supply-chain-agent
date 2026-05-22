from __future__ import annotations

import hashlib

from opentelemetry.sdk._logs import LogRecordProcessor

from .pii import REDACT_ATTRS


class PIIRedactionLogProcessor(LogRecordProcessor):
    """Redacts PII from log record attributes before export.

    Mirrors PIIRedactionProcessor for spans; reuses REDACT_ATTRS so a new
    free-text attribute added to pii.py covers both spans and logs (§6.4).
    """

    def on_emit(self, log_record) -> None:
        # The SDK wraps the API LogRecord in ReadWriteLogRecord; attributes live on .log_record
        attrs = getattr(getattr(log_record, "log_record", None), "attributes", None)
        if not attrs:
            return
        for attr in REDACT_ATTRS:
            if attr in attrs:
                raw = str(attrs[attr])
                attrs[attr] = "redacted:" + hashlib.sha256(raw.encode()).hexdigest()[:12]

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True
