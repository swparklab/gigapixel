import json
import logging

from app.errors import PipelineError, ResourceLimitError, WorkflowError
from app.logging_config import JsonLogFormatter
from app.services.exporter import sanitize_filename


def test_error_hierarchy_carries_context():
    error = ResourceLimitError("too large", context={"pixels": 123})

    assert isinstance(error, PipelineError)
    assert error.code == "resource_limit_error"
    assert error.context["pixels"] == 123
    assert str(WorkflowError("bad graph")) == "bad graph"


def test_sanitize_filename_falls_back_to_session():
    assert sanitize_filename("../bad name.tif") == "bad_name.tif"
    assert sanitize_filename("???") == "session"


def test_json_log_formatter_includes_extra_fields():
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.job_id = 42

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["message"] == "hello"
    assert payload["job_id"] == 42

