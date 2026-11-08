"""참여자별 상태 머신(IDLE → IN_PROGRESS → COMPLETE)으로 시작·종료를 연결한다."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from prayer_tracker.config import Settings
from prayer_tracker.models import (
    ClassificationSource, Confidence, Event, EventType, Message, Review, ReviewType,
    Session, SessionStatus,
)


def logical_date(t: datetime, grace_hour: int):
    """검토 항목 표시용 날짜(04:00 이전은 전날)."""
    return (t - timedelta(hours=grace_hour)).date()


def _can_auto_confirm(ev: Event, expect: EventType, settings: Settings) -> bool:
    if ev.event_type != EventType.AMBIGUOUS or ev.candidate != expect or ev.confidence != Confidence.MEDIUM:
        return False
    if ev.matched_rule == "bare_end":
        return settings.auto_confirm_bare_end_in_session
    if ev.matched_rule == "bare_start":
        return settings.auto_confirm_bare_start
    if ev.matched_rule == "start_pray_bare":
        return False   # 뒤따르는 종료를 보고 match_member에서 판단한다(_end_follows)
    if ev.matched_rule.startswith(("start_suffix", "end_suffix")):
        return settings.auto_confirm_suffix_in_context
    return settings.auto_confirm_typo_in_context


def _is_end_like(ev: Event) -> bool:
    return ev.event_type == EventType.END or (
        ev.event_type == EventType.AMBIGUOUS and ev.candidate == EventType.END
        and ev.confidence == Confidence.MEDIUM)


def _end_follows(items: list[tuple[Message, Event]], i: int, linked: set[str], max_gap: timedelta) -> bool:
    """i번째 이후 같은 사람의 다음 인증 관련 메시지가 max_gap 안의 종료(확정 또는 MEDIUM 후보)인가."""
    t0 = items[i][0].sent_at
    for m, e in items[i + 1:]:
        if m.id in linked or e.event_type == EventType.OTHER:
            continue
        return _is_end_like(e) and t0 < m.sent_at <= t0 + max_gap
    return False


def match_member(
    member_id: int,
    items: list[tuple[Message, Event]],
    coverage_end: datetime | None,
    settings: Settings,
    manual_links: list[tuple[str, str]] = (),
) -> tuple[list[Session], list[Review], dict[str, Event]]:
    """items: 한 참여자의 (메시지, 이벤트)를 시간순으로. OTHER 포함 가능.
    반환: 세션, 검토 항목, 문맥에 의해 갱신된 이벤트."""
    max_gap = timedelta(hours=settings.max_session_hours)
    dup_end = timedelta(minutes=settings.duplicate_end_minutes)
    gh = settings.grace_hour
    msgs = {m.id: m for m, _ in items}
    updated: dict[str, Event] = {}
    sessions: list[Session] = []
    reviews: list[Review] = []

    # 관리자가 직접 연결한 세션
    linked: set[str] = set()
    for s_id, e_id in manual_links:
        if s_id in msgs and e_id in msgs:
            sm, em = msgs[s_id], msgs[e_id]
            linked.update((s_id, e_id))
            ok = em.sent_at > sm.sent_at
            sessions.append(Session(member_id, s_id, e_id, sm.sent_at, em.sent_at,
                                    SessionStatus.COMPLETE if ok else SessionStatus.INCOMPLETE, manual=True))

    open_s: Session | None = None
    open_end_cands: list[str] = []
    last_complete: Session | None = None
    pending: list[tuple[Message, Event]] = []   # 미확정 후보

    def close_incomplete(s: Session):
        s.status = SessionStatus.INCOMPLETE
        # 종료 후보가 없으면 검토 없이 INCOMPLETE로 표시(TC-11). 후보가 있으면 관리자 확인.
        if open_end_cands:
            reviews.append(Review(ReviewType.MISSING_END, member_id, logical_date(s.start_at, gh),
                                  [s.start_message_id, *open_end_cands],
                                  "시작 메시지는 명확하지만 종료가 불명확함 — 종료 후보를 확인해 주세요",
                                  session_key=s.key))

    def confirm(ev: Event, et: EventType) -> Event:
        if ev.event_type == et:
            return ev
        new = replace(ev, event_type=et, source=ClassificationSource.CONTEXT
                      if ev.source == ClassificationSource.CONTEXT else ev.source)
        updated[ev.message_id] = new
        return new

    for idx, (msg, ev) in enumerate(items):
        if msg.id in linked or ev.event_type == EventType.OTHER:
            continue
        t = msg.sent_at
        # 진행 중 세션이 너무 오래되면 종료 누락으로 닫는다
        if open_s and t - open_s.start_at > max_gap:
            close_incomplete(open_s)
            open_s, open_end_cands = None, []

        restart = "restart" in ev.matched_rule
        is_start = ev.event_type == EventType.START or (
            (open_s is None or restart) and _can_auto_confirm(ev, EventType.START, settings))
        if (not is_start and open_s is None and ev.matched_rule == "start_pray_bare"
                and ev.event_type == EventType.AMBIGUOUS and ev.confidence == Confidence.MEDIUM
                and settings.auto_confirm_pray_start_before_end and _end_follows(items, idx, linked, max_gap)):
            is_start = True
        is_end = ev.event_type == EventType.END or (open_s is not None and _can_auto_confirm(ev, EventType.END, settings))

        if is_start:
            ev = confirm(ev, EventType.START)
            if open_s is not None and restart:
                # "다시 기도 시작합니다": 앞선 시작은 중단된 것으로 보고 재시작 지점부터 새 세션 (결정 #4)
                open_s.status = SessionStatus.INCOMPLETE
                open_s = None
            if open_s is None:
                open_s = Session(member_id, msg.id, None, t, None, SessionStatus.IN_PROGRESS)
                sessions.append(open_s)
                open_end_cands = []
            else:
                reviews.append(Review(ReviewType.DUPLICATE_START, member_id, logical_date(open_s.start_at, gh),
                                      [open_s.start_message_id, msg.id],
                                      "종료 전에 시작 메시지가 다시 발생함", session_key=open_s.key))
        elif is_end:
            ev = confirm(ev, EventType.END)
            if open_s is not None:
                if t <= open_s.start_at:
                    reviews.append(Review(ReviewType.AMBIGUOUS, member_id, logical_date(open_s.start_at, gh),
                                          [open_s.start_message_id, msg.id],
                                          "종료 시각이 시작 시각보다 늦지 않음(같은 분)", session_key=open_s.key))
                    continue
                open_s.end_message_id, open_s.end_at = msg.id, t
                open_s.status = SessionStatus.COMPLETE
                last_complete, open_s, open_end_cands = open_s, None, []
            elif last_complete and t - last_complete.end_at <= dup_end:
                reviews.append(Review(ReviewType.DUPLICATE_END, member_id, logical_date(last_complete.start_at, gh),
                                      [last_complete.end_message_id, msg.id],
                                      "세션 종료 직후 종료 메시지가 다시 발생함", session_key=last_complete.key))
            else:
                cands = [m.id for m, e in pending
                         if e.candidate == EventType.START and t - max_gap <= m.sent_at < t]
                pending = [(m, e) for m, e in pending if m.id not in cands]
                reviews.append(Review(ReviewType.MISSING_START, member_id, logical_date(t, gh),
                                      [*cands, msg.id],
                                      "종료 메시지는 명확하지만 시작이 확인되지 않음"
                                      + (" — 시작 후보를 확인해 주세요" if cands else "")))
        else:
            if open_s is not None and ev.candidate == EventType.END:
                open_end_cands.append(msg.id)
            else:
                pending.append((msg, ev))

    if open_s is not None:
        if coverage_end is not None and coverage_end - open_s.start_at < max_gap and not open_end_cands:
            open_s.status = SessionStatus.IN_PROGRESS   # 아직 종료 메시지가 수집되지 않았을 수 있음
        else:
            close_incomplete(open_s)

    for m, e in pending:
        what = {EventType.START: "시작", EventType.END: "종료"}.get(e.candidate, "인증")
        reviews.append(Review(ReviewType.AMBIGUOUS, member_id, logical_date(m.sent_at, gh), [m.id],
                              f"{what} 후보로 보이지만 의미가 불확실함 ({e.matched_rule})"))
    return sessions, reviews, updated
