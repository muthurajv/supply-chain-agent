"""Unit tests for PIIRedactionLogProcessor — mirrors test_pii_redaction.py for spans."""
from __future__ import annotations

import hashlib

import pytest
from opentelemetry._logs import LogRecord, SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor

from app.observability.log_processor import PIIRedactionLogProcessor
from app.observability.pii import REDACT_ATTRS


@pytest.fixture
def redacting_log_setup():
    """LoggerProvider with PIIRedactionLogProcessor upstream of InMemoryLogRecordExporter."""
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(PIIRedactionLogProcessor())
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    logger = provider.get_logger("test")
    yield exporter, logger
    provider.shutdown()


def _emit(logger, body: str, attributes: dict) -> None:
    logger.emit(LogRecord(body=body, attributes=attributes, severity_number=SeverityNumber.INFO))


def _attrs(record) -> dict:
    """Extract attributes from a finished log record (SDK wraps in ReadWriteLogRecord)."""
    return record.log_record.attributes or {}


class TestPIIRedactionLogProcessor:
    def test_user_email_is_redacted(self, redacting_log_setup):
        exporter, logger = redacting_log_setup
        _emit(logger, "test", {"user.email": "alice@example.com"})
        records = exporter.get_finished_logs()
        assert len(records) == 1
        assert _attrs(records[0])["user.email"].startswith("redacted:")

    def test_redacted_value_matches_sha256_hash(self, redacting_log_setup):
        exporter, logger = redacting_log_setup
        raw = "bob@example.com"
        _emit(logger, "test", {"user.email": raw})
        record = exporter.get_finished_logs()[0]
        expected = "redacted:" + hashlib.sha256(raw.encode()).hexdigest()[:12]
        assert _attrs(record)["user.email"] == expected

    def test_non_pii_attribute_passes_through_unchanged(self, redacting_log_setup):
        exporter, logger = redacting_log_setup
        _emit(logger, "test", {"http.route": "/chat"})
        record = exporter.get_finished_logs()[0]
        assert _attrs(record)["http.route"] == "/chat"

    def test_rag_query_is_redacted(self, redacting_log_setup):
        exporter, logger = redacting_log_setup
        _emit(logger, "test", {"rag.query": "vendor procurement cost"})
        record = exporter.get_finished_logs()[0]
        assert _attrs(record)["rag.query"].startswith("redacted:")

    def test_absent_pii_attr_does_not_error(self, redacting_log_setup):
        exporter, logger = redacting_log_setup
        _emit(logger, "test", {"http.route": "/healthz"})
        records = exporter.get_finished_logs()
        assert len(records) == 1

    def test_redaction_is_deterministic(self, redacting_log_setup):
        exporter, logger = redacting_log_setup
        raw = "alice@example.com"
        _emit(logger, "first", {"user.email": raw})
        _emit(logger, "second", {"user.email": raw})
        records = exporter.get_finished_logs()
        assert _attrs(records[0])["user.email"] == _attrs(records[1])["user.email"]

    @pytest.mark.parametrize("attr", sorted(REDACT_ATTRS))
    def test_every_redact_attr_is_redacted(self, redacting_log_setup, attr):
        exporter, logger = redacting_log_setup
        _emit(logger, "test", {attr: "sensitive-value"})
        record = exporter.get_finished_logs()[0]
        assert _attrs(record)[attr].startswith("redacted:")

    def test_shutdown_does_not_raise(self):
        processor = PIIRedactionLogProcessor()
        processor.shutdown()

    def test_force_flush_returns_true(self):
        processor = PIIRedactionLogProcessor()
        assert processor.force_flush() is True
