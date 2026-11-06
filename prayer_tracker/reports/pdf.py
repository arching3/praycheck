"""PDF 생성기: 기간의 날짜마다 템플릿을 적용해 하루 1페이지 PDF를 만든다."""
from __future__ import annotations

import io
from datetime import date, timedelta

from prayer_tracker.reports.day_report import day_report_data
from prayer_tracker.reports.pdf_template import DayReportTemplate, render_day


def day_png(service, d: date, template: DayReportTemplate | None = None) -> bytes:
    buf = io.BytesIO()
    render_day(day_report_data(service, d), template).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def build_pdf(service, start: date, end: date, template: DayReportTemplate | None = None) -> bytes:
    t = template or DayReportTemplate()
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    pages = [render_day(day_report_data(service, d), t, page=(i + 1, len(days))) for i, d in enumerate(days)]
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:], resolution=t.dpi,
                  title=f"{t.title} {start}~{end}")
    return buf.getvalue()
