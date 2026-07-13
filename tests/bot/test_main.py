"""Bot process configuration tests."""

import logging

from course_platform.bot.__main__ import configure_logging


def test_http_client_logs_are_suppressed_to_protect_token_urls() -> None:
    configure_logging("INFO")

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
