"""날짜 귀속. 새벽(00:00~04:00) 시작 세션은 전날 상태에 따라 동적으로 귀속한다."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from prayer_tracker.models import Coverage, DateSource, Review, ReviewType, Session, SessionStatus


def merge_coverage(cov: list[Coverage]) -> list[Coverage]:
    out: list[Coverage] = []
    for c in sorted(cov, key=lambda c: c.start):
        if out and c.start <= out[-1].end:
            out[-1] = Coverage(out[-1].start, max(out[-1].end, c.end))
        else:
            out.append(Coverage(c.start, c.end))
    return out


def is_covered(cov: list[Coverage], start: datetime, end: datetime) -> bool:
    """[start, end] 구간 전체가 수집 데이터로 덮였는가 (cov는 병합된 상태)."""
    return any(c.start <= start and c.end >= end for c in cov)


def assign_member(
    sessions: list[Session],
    coverage: list[Coverage],
    tracking_start: date,
    grace_hour: int,
    overrides: dict[str, date],
) -> list[Review]:
    """한 참여자의 세션에 prayer_date를 채운다(제자리 수정). 시간순 처리로 결과가 결정적이다."""
    reviews: list[Review] = []
    complete_days: set[date] = set()
    open_days: set[date] = set()
    for s in sorted((s for s in sessions if s.start_at), key=lambda s: s.start_at):
        d = s.start_at.date()
        if s.manual_id is not None:
            pass   # 관리자가 입력한 귀속 날짜를 그대로 쓴다
        elif s.start_message_id in overrides:
            s.prayer_date, s.date_source = overrides[s.start_message_id], DateSource.ADMIN
        elif s.start_at.hour >= grace_hour:
            s.prayer_date, s.date_source = d, DateSource.START_DATE
        else:
            prev = d - timedelta(days=1)
            if prev < tracking_start:
                # 결정 #2: 추적 시작일 이전 날짜의 새벽 인증은 집계하지 않는다.
                s.prayer_date, s.date_source = prev, DateSource.OUT_OF_RANGE
            elif not is_covered(coverage, datetime.combine(prev, time(grace_hour)), s.start_at):
                s.prayer_date, s.date_source = None, DateSource.PENDING
                reviews.append(Review(ReviewType.DATE_ASSIGNMENT, s.member_id, prev, [s.start_message_id],
                                      f"전날({prev}) 대화 내역이 수집되지 않아 날짜 귀속을 판단할 수 없음",
                                      session_key=s.key))
            elif prev in complete_days:
                s.prayer_date, s.date_source = d, DateSource.SAME_DAY
            elif prev in open_days:
                s.prayer_date, s.date_source = None, DateSource.PENDING
                reviews.append(Review(ReviewType.DATE_ASSIGNMENT, s.member_id, prev, [s.start_message_id],
                                      f"전날({prev})에 종료되지 않은 세션이 있어 귀속 날짜를 판단할 수 없음",
                                      session_key=s.key))
            else:
                s.prayer_date, s.date_source = prev, DateSource.PREV_DAY
        if s.prayer_date is not None:
            (complete_days if s.status == SessionStatus.COMPLETE else open_days).add(s.prayer_date)
    return reviews
