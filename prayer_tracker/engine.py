"""전체 분석 파이프라인. 순수 함수: (원본 메시지 + 관리자 판정 + 설정) → 결과.

같은 입력이면 업로드 순서와 무관하게 항상 같은 결과를 낸다(PRD 11.3).
관리자 판정은 입력으로만 쓰이며 자동 분석이 덮어쓰지 않는다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from prayer_tracker.assignment.dates import assign_member, is_covered, merge_coverage
from prayer_tracker.classification.classifier import classify_message
from prayer_tracker.config import Settings
from prayer_tracker.models import (
    AnalysisResult, ClassificationSource, Confidence, Coverage, DateSource, DayStatus, Event,
    EventType, ManualRecord, Message, Session, SessionStatus,
)
from prayer_tracker.sessions.matcher import match_member


@dataclass
class AdminDecisions:
    labels: dict[str, EventType] = field(default_factory=dict)          # message_id → START/END/OTHER
    links: list[tuple[str, str]] = field(default_factory=list)          # (start_id, end_id)
    date_overrides: dict[str, date] = field(default_factory=dict)       # start_message_id → date
    review_status: dict[str, str] = field(default_factory=dict)         # review.key → HELD/RESOLVED/NO_CANDIDATE
    manual_records: list[ManualRecord] = field(default_factory=list)    # 관리자 수동 기록


def tracking_start_of(settings: Settings, coverage: list[Coverage]) -> date | None:
    if settings.tracking_start_date:
        return settings.tracking_start_date
    return min((c.start.date() for c in coverage), default=None)


def analyze(
    messages: list[Message],
    targets: set[int],
    coverage: list[Coverage],
    decisions: AdminDecisions | None = None,
    settings: Settings | None = None,
) -> AnalysisResult:
    settings = settings or Settings()
    decisions = decisions or AdminDecisions()
    coverage = merge_coverage(coverage)
    result = AnalysisResult()
    start_day = tracking_start_of(settings, coverage)
    if start_day is None or not coverage:
        return result
    coverage_end = max(c.end for c in coverage)

    by_member: dict[int, list[tuple[Message, Event]]] = defaultdict(list)
    for m in sorted(messages, key=lambda m: m.sort_key):
        if m.member_id not in targets:
            continue
        if m.id in decisions.labels:
            ev = Event(m.id, decisions.labels[m.id], Confidence.HIGH, ClassificationSource.ADMIN, "admin")
        else:
            ev = classify_message(m, settings)
        result.events[m.id] = ev
        by_member[m.member_id].append((m, ev))

    manual_by_member: dict[int, list[Session]] = defaultdict(list)
    for mr in decisions.manual_records:
        if mr.member_id in targets:
            manual_by_member[mr.member_id].append(Session(
                mr.member_id, None, None, mr.start_at, mr.end_at, SessionStatus.COMPLETE,
                prayer_date=mr.prayer_date, date_source=DateSource.ADMIN, manual_id=mr.id))

    for member_id in sorted(set(by_member) | set(manual_by_member)):
        items = by_member.get(member_id, [])
        links = [l for l in decisions.links if l[0] in {m.id for m, _ in items}]
        sessions, reviews, updated = match_member(member_id, items, coverage_end, settings, links)
        # 수동 기록도 시간순 날짜 귀속에 참여한다(전날 완료 여부 판단에 반영)
        sessions += manual_by_member.get(member_id, [])
        result.events.update(updated)
        reviews += assign_member(sessions, coverage, start_day, settings.grace_hour, decisions.date_overrides)
        result.sessions += sessions
        result.reviews += reviews

    # 추적 시작일 이전 검토는 제외(결정 #2), 관리자 결정 상태 적용
    oor = {s.key for s in result.sessions if s.date_source == DateSource.OUT_OF_RANGE}
    kept = []
    for r in result.reviews:
        if (r.target_date and r.target_date < start_day) or r.session_key in oor:
            continue
        r.status = decisions.review_status.get(r.key, "OPEN")
        kept.append(r)
    result.reviews = kept

    result.day_status = compute_day_status(result, targets, coverage, start_day, settings.grace_hour)
    return result


def day_range(coverage: list[Coverage], start_day: date) -> list[date]:
    if not coverage:
        return []
    end = max(c.end for c in coverage).date()
    return [start_day + timedelta(days=i) for i in range((end - start_day).days + 1)]


def compute_day_status(result: AnalysisResult, targets: set[int], coverage: list[Coverage],
                       start_day: date, grace_hour: int) -> dict:
    """상태 우선순위: COMPLETE > PENDING_REVIEW > PENDING_DATA(진행 중/미수집) > INCOMPLETE > MISSING.
    각 (참여자, 날짜)는 정확히 하나의 상태 → 요약 집계가 중복되지 않는다."""
    sess = defaultdict(list)
    for s in result.sessions:
        if s.prayer_date and s.date_source != DateSource.OUT_OF_RANGE:
            sess[(s.member_id, s.prayer_date)].append(s)
    open_reviews = {(r.member_id, r.target_date) for r in result.reviews if r.status in ("OPEN", "HELD")}
    out = {}
    for d in day_range(coverage, start_day):
        window_covered = is_covered(coverage, datetime.combine(d, time(0)),
                                    datetime.combine(d + timedelta(days=1), time(grace_hour)))
        for mid in targets:
            ss = sess.get((mid, d), [])
            if any(s.status == SessionStatus.COMPLETE for s in ss):
                st = DayStatus.COMPLETE
            elif (mid, d) in open_reviews:
                st = DayStatus.PENDING_REVIEW
            elif any(s.status == SessionStatus.IN_PROGRESS for s in ss) or not window_covered:
                st = DayStatus.PENDING_DATA
            elif ss:
                st = DayStatus.INCOMPLETE
            else:
                st = DayStatus.MISSING
            out[(mid, d)] = st
    return out
