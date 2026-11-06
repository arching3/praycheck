"""일자별 보고서 데이터. 템플릿(pdf_template)은 이 구조만 보고 그린다."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from prayer_tracker.models import DateSource, DayStatus, SessionStatus
from prayer_tracker.reports.summary import STATUS_KO, fmt_duration


@dataclass
class SessionLine:
    start: str            # "21:23" / 다른 날짜면 "익일 01:16"
    end: str              # 종료 없으면 "—"
    duration: str         # "30분" / 미완료면 ""
    complete: bool
    manual: bool = False  # 관리자 수동 기록


@dataclass
class MemberRow:
    name: str
    status: DayStatus | None
    status_label: str     # 완료 / 미완료 / 미인증 / 검토 대기 / 데이터 확인 대기
    sessions: list[SessionLine] = field(default_factory=list)
    total: str = ""       # 완료 세션 합계


@dataclass
class DayReport:
    day: date
    rows: list[MemberRow]
    counts: dict[str, int]          # 상태 라벨 → 인원
    generated_at: datetime


def _clock(t: datetime | None, d: date) -> str:
    if t is None:
        return "—"
    if t.date() == d:
        return f"{t:%H:%M}"
    return f"{'익일' if t.date() > d else '전일'} {t:%H:%M}"


def day_report_data(service, d: date) -> DayReport:
    res = service.result
    names = service.member_names()
    rows = []
    for mid in sorted(service.targets(), key=lambda i: names.get(i, "")):
        status = res.day_status.get((mid, d))
        ss = sorted((s for s in res.sessions if s.member_id == mid and s.prayer_date == d
                     and s.date_source != DateSource.OUT_OF_RANGE and s.start_at),
                    key=lambda s: s.start_at)
        lines = [SessionLine(_clock(s.start_at, d), _clock(s.end_at, d), fmt_duration(s.duration_seconds),
                             s.status == SessionStatus.COMPLETE, s.manual_id is not None) for s in ss]
        total = sum(s.duration_seconds or 0 for s in ss if s.status == SessionStatus.COMPLETE)
        rows.append(MemberRow(names.get(mid, str(mid)), status, STATUS_KO.get(status, "-") if status else "-",
                              lines, fmt_duration(total) if total else ""))
    counts = {label: sum(r.status == st for r in rows) for st, label in STATUS_KO.items()}
    return DayReport(d, rows, counts, datetime.now())
