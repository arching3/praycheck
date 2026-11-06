"""일자별 PDF 보고서: 데이터 → 템플릿 → PDF."""
from datetime import date

import pytest

from prayer_tracker.models import DayStatus
from prayer_tracker.reports.day_report import day_report_data
from prayer_tracker.reports.pdf import build_pdf, day_png
from prayer_tracker.reports.pdf_template import DayReportTemplate, find_font, render_day
from prayer_tracker.service import PrayerService

EXPORT = """저장한 날짜 : 2026-10-28 09:00:00
--------------- 2026년 10월 26일 월요일 ---------------
[참여자A] [오후 10:00] 기도 시작합니다
[참여자A] [오후 10:30] 기도 마칩니다
[참여자B] [오후 11:40] 기도 시작합니다
[참여자C] [오후 9:00] 기도 시작합니다
[참여자D] [오후 9:00] 안녕하세요
--------------- 2026년 10월 27일 화요일 ---------------
[참여자B] [오전 12:20] 기도 마칩니다
""".encode("utf-8")

try:
    find_font("regular")
    HAS_FONT = True
except FileNotFoundError:
    HAS_FONT = False
needs_font = pytest.mark.skipif(not HAS_FONT, reason="한글 글꼴 없음")


@pytest.fixture
def svc():
    s = PrayerService(":memory:")
    s.save_settings(s.get_settings().model_copy(update={"tracking_start_date": date(2026, 10, 26)}))
    s.import_file("a.txt", EXPORT)
    s.set_targets({m["id"] for m in s.members()})
    return s


def test_day_report_rows(svc):
    rep = day_report_data(svc, date(2026, 10, 26))
    rows = {r.name: r for r in rep.rows}
    a = rows["참여자A"].sessions[0]
    assert rows["참여자A"].status == DayStatus.COMPLETE and (a.start, a.end, a.duration) == ("22:00", "22:30", "30분")
    b = rows["참여자B"].sessions[0]   # 자정을 넘긴 세션: 종료 시각에 '익일' 표시
    assert (b.start, b.end, b.duration) == ("23:40", "익일 00:20", "40분")
    c = rows["참여자C"]               # 종료 없음 → 시간 추정 금지
    assert c.status == DayStatus.INCOMPLETE and (c.sessions[0].end, c.sessions[0].duration) == ("—", "")
    assert rows["참여자D"].sessions == [] and rows["참여자D"].status == DayStatus.MISSING
    assert rep.counts["완료"] == 2 and sum(rep.counts.values()) == len(rep.rows) == 4


@needs_font
def test_render_day_size_and_template_override(svc):
    rep = day_report_data(svc, date(2026, 10, 26))
    assert render_day(rep).size == (1240, 1754)
    assert render_day(rep, DayReportTemplate(width=800, height=1130, margin=50)).size == (800, 1130)


@needs_font
def test_pdf_has_one_page_per_day(svc):
    data = build_pdf(svc, date(2026, 10, 26), date(2026, 10, 27))
    assert data.startswith(b"%PDF") and data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") >= 2


@needs_font
def test_day_png(svc):
    assert day_png(svc, date(2026, 10, 26)).startswith(b"\x89PNG")
