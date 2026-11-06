import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prayer_tracker.models import Coverage, Message, MessageType  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
_counter = {"n": 0}


def dt(day: int, hh: int, mm: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hh, mm)


def msg(text, day, hh, mm=0, member=1, mtype=MessageType.TEXT, seq=0, mid=None) -> Message:
    """Message 빠르게 만들기. 2026-10-<day> hh:mm."""
    _counter["n"] += 1
    return Message(
        id=mid or f"m{_counter['n']:05d}", sender_raw=f"p{member}", sent_at=dt(day, hh, mm),
        raw_text=text, message_type=mtype, seq=seq, member_id=member,
    )


def cov(first_day: int, last_day: int, last_hh: int = 23, last_mm: int = 59) -> Coverage:
    """첫 날 00:00 ~ 마지막 날 last_hh:last_mm."""
    return Coverage(dt(first_day, 0), dt(last_day, last_hh, last_mm))


@pytest.fixture
def sample_text() -> str:
    return (FIXTURES / "sample_chat.txt").read_text(encoding="utf-8")


@pytest.fixture
def make_msg():
    return msg


@pytest.fixture
def make_cov():
    return cov
