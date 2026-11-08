import logging

import pytest

from app.logging_config import configure_logging


@pytest.fixture(autouse=True)
def restore_root():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:], root.level = handlers, level


def test_sets_the_level_by_name_and_installs_one_handler():
    configure_logging("debug")
    configure_logging("WARNING")  # again: no duplicate handlers
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert len([h for h in root.handlers if getattr(h, "_comm_center", False)]) == 1


def test_lines_carry_time_level_logger_and_message(capfd):
    configure_logging("INFO")
    logging.getLogger("app.test").info("hello %s", "there")
    err = capfd.readouterr().err
    assert " INFO app.test: hello there" in err


def test_an_unknown_level_is_an_error_not_silence():
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        configure_logging("loud")
