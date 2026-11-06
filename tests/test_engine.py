import random
from datetime import date

import pytest

from conftest import cov, dt, msg
from prayer_tracker.config import Settings
from prayer_tracker.engine import AdminDecisions, analyze
from prayer_tracker.ingestion.parser import parse_text
from prayer_tracker.models import (
    Coverage, DateSource, DayStatus, EventType, ReviewType, SessionStatus,
)

START, END = "기도 시작합니다", "기도 마칩니다"
D26, D27, D28 = date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)


def run(msgs, last_day=26, decisions=None, settings=None, first_day=26, targets=None, coverage=None):
    return analyze(msgs, targets or {1}, coverage or [Coverage(dt(first_day, 0), dt(last_day + 1, 4))], decisions, settings)


def completes(res):
    return [s for s in res.sessions if s.status == SessionStatus.COMPLETE]


def test_tc01_explicit_start_end():
    a, b = msg(START, 26, 22, 19), msg(END, 26, 22, 49)
    res = run([a, b])
    assert res.events[a.id].event_type == EventType.START
    assert res.events[b.id].event_type == EventType.END
    (s,) = res.sessions
    assert s.duration_seconds == 1800 and s.prayer_date == D26
    assert res.day_status[(1, D26)] == DayStatus.COMPLETE
    assert res.reviews == []


def test_tc02_typo_end_auto_matched_in_context():
    res = run([msg(START, 26, 22, 19), msg("ㄱ도 마칩니다", 26, 22, 49)])
    assert completes(res)[0].duration_seconds == 1800


def test_tc02_typo_end_goes_to_review_when_auto_confirm_off_then_admin_approves():
    a, b = msg(START, 26, 22, 19), msg("ㄱ도 마칩니다", 26, 22, 49)
    st = Settings(auto_confirm_typo_in_context=False)
    res = run([a, b], settings=st)
    assert not completes(res) and res.reviews
    res2 = run([a, b], settings=st, decisions=AdminDecisions(labels={b.id: EventType.END}))
    assert completes(res2)[0].duration_seconds == 1800


def test_tc03_colloquial_expressions_matched():
    res = run([msg("기도시작합니당", 26, 22, 0), msg("마쳤습니다아", 26, 22, 30)])
    assert len(completes(res)) == 1


def test_tc04_uc02_loose_start_admin_label_makes_30_min_session():
    a, b = msg("무튼 기도합니다", 26, 22, 56), msg(END, 26, 23, 26)
    res = run([a, b])
    assert not completes(res)
    missing = [r for r in res.reviews if r.review_type == ReviewType.MISSING_START]
    assert missing and a.id in missing[0].message_ids
    assert res.day_status[(1, D26)] == DayStatus.PENDING_REVIEW

    res2 = run([a, b], decisions=AdminDecisions(labels={a.id: EventType.START}))
    (s,) = completes(res2)
    assert s.duration_seconds == 1800
    assert res2.day_status[(1, D26)] == DayStatus.COMPLETE
    assert res2.reviews == []


def test_admin_link_makes_session_without_labels():
    a, b = msg("무튼 기도합니다", 26, 22, 56), msg(END, 26, 23, 26)
    res = run([a, b], decisions=AdminDecisions(links=[(a.id, b.id)]))
    assert completes(res)[0].duration_seconds == 1800


def test_tc05_prayer_response_creates_no_session():
    m = msg("기도했습니다! 조금 뒤에 더 길게 기도할 때에도 기도하겠습니다~!", 26, 22)
    res = run([m])
    assert res.sessions == []
    assert res.events[m.id].event_type in (EventType.OTHER, EventType.AMBIGUOUS)
    assert res.day_status[(1, D26)] != DayStatus.COMPLETE


def test_bare_end_without_open_session_no_completed_session():
    res = run([msg("마칩니다", 26, 22)])
    assert not completes(res)
    assert res.day_status[(1, D26)] != DayStatus.COMPLETE


def test_bare_end_with_open_session_completes():
    res = run([msg(START, 26, 22, 0), msg("마쳤습니다", 26, 22, 30)])
    assert len(completes(res)) == 1 and res.reviews == []


def test_tc06_multiline_message_start():
    a = msg("아주 좋아요~~\n기도시작합니다", 26, 22, 19)
    res = run([a, msg(END, 26, 22, 49)])
    assert res.events[a.id].event_type == EventType.START
    assert len(completes(res)) == 1


def test_tc07_midnight_crossing_belongs_to_start_day():
    res = run([msg(START, 27, 23, 45), msg(END, 28, 0, 19)], last_day=28)
    (s,) = res.sessions
    assert s.prayer_date == D27
    assert (s.start_at, s.end_at) == (dt(27, 23, 45), dt(28, 0, 19))
    assert res.day_status[(1, D27)] == DayStatus.COMPLETE
    assert res.day_status[(1, D28)] == DayStatus.MISSING


def test_tc08_dawn_attributed_to_previous_uncertified_day():
    res = run([msg(START, 28, 3, 0), msg(END, 28, 3, 30)], last_day=28)
    (s,) = res.sessions
    assert s.prayer_date == D27 and s.date_source == DateSource.PREV_DAY
    assert res.day_status[(1, D27)] == DayStatus.COMPLETE
    assert res.day_status[(1, D28)] == DayStatus.MISSING


def test_tc08_dawn_attributed_to_same_day_when_previous_complete():
    msgs = [msg(START, 27, 22, 0), msg(END, 27, 22, 30), msg(START, 28, 3, 0), msg(END, 28, 3, 30)]
    res = run(msgs, last_day=28)
    dawn = [s for s in res.sessions if s.start_at.hour == 3][0]
    assert dawn.prayer_date == D28 and dawn.date_source == DateSource.SAME_DAY
    assert res.day_status[(1, D27)] == DayStatus.COMPLETE
    assert res.day_status[(1, D28)] == DayStatus.COMPLETE


def test_tc09_0400_is_same_day():
    res = run([msg(START, 28, 4, 0), msg(END, 28, 4, 30)], last_day=28)
    assert res.sessions[0].prayer_date == D28
    assert res.day_status[(1, D28)] == DayStatus.COMPLETE
    assert res.day_status[(1, D27)] == DayStatus.MISSING


def test_0359_start_ending_0430_counts_for_previous_day():
    res = run([msg(START, 28, 3, 59), msg(END, 28, 4, 30)], last_day=28)
    assert res.sessions[0].prayer_date == D27


def test_tc10_first_day_dawn_out_of_range_no_review_no_claim():
    res = run([msg(START, 26, 0, 13), msg(END, 26, 0, 43)], last_day=26)
    (s,) = res.sessions
    assert s.date_source == DateSource.OUT_OF_RANGE
    assert res.reviews == []
    assert res.day_status[(1, D26)] == DayStatus.MISSING
    assert (1, date(2026, 10, 25)) not in res.day_status


def test_tc10_explicit_earlier_tracking_start_requires_date_review():
    res = run([msg(START, 26, 0, 13), msg(END, 26, 0, 43)], last_day=26,
              settings=Settings(tracking_start_date=date(2026, 10, 25)))
    assert [r.review_type for r in res.reviews] == [ReviewType.DATE_ASSIGNMENT]
    sunday = res.day_status[(1, date(2026, 10, 25))]
    assert sunday != DayStatus.MISSING
    assert sunday in (DayStatus.PENDING_REVIEW, DayStatus.PENDING_DATA)


def test_tc11_missing_end_is_incomplete():
    res = run([msg(START, 26, 22, 30)], last_day=28)
    (s,) = res.sessions
    assert s.status == SessionStatus.INCOMPLETE
    assert s.end_at is None and s.duration_seconds is None
    assert res.reviews == []
    assert res.day_status[(1, D26)] == DayStatus.INCOMPLETE


def test_day_not_yet_closed_by_data_is_pending_data():
    """당일 종료 후 다음날 04:00까지 수집되지 않았으면 MISSING 단정 금지."""
    res = run([], coverage=[cov(26, 26)])
    assert res.day_status[(1, D26)] == DayStatus.PENDING_DATA


def test_tc11_latest_start_with_fresh_data_is_pending():
    res = run([msg(START, 26, 22, 30)], last_day=26)
    assert res.day_status[(1, D26)] == DayStatus.PENDING_DATA


def test_tc12_duplicate_upload_no_duplicates(sample_text):
    parsed = parse_text(sample_text).messages
    twice = parsed + parse_text(sample_text).messages
    unique = {m.id: m for m in twice}
    assert len(unique) == len(parsed)


def _sample_messages(text):
    members = {"참여자A": 1, "참여자B": 2, "참여자C": 3, "참여자D": 4, "참여자E": 5}
    msgs = parse_text(text).messages
    for m in msgs:
        m.member_id = members.get(m.sender_raw)
    return msgs


def test_sample_fixture_end_to_end(sample_text):
    msgs = _sample_messages(sample_text)
    res = analyze(msgs, {1, 2, 3, 4, 5}, [Coverage(dt(26, 0), dt(28, 4))])
    # A: 월요일 새벽 첫날 → 집계 제외
    assert res.day_status[(1, D26)] == DayStatus.MISSING
    # B: 정상 30분
    assert res.day_status[(2, D26)] == DayStatus.COMPLETE
    # C: 같은 메시지 안의 "기도시작합니다" → 종료 없음 → INCOMPLETE
    assert res.day_status[(3, D26)] == DayStatus.INCOMPLETE
    # D: "무튼 기도합니다" → 검토 대기
    assert res.day_status[(4, D26)] == DayStatus.PENDING_REVIEW
    # E: 화요일 23:45 → 수요일 00:19 은 화요일에 귀속
    assert res.day_status[(5, D27)] == DayStatus.COMPLETE
    # 비대상자(member_id None)는 결과에 없음
    assert all(k[0] in {1, 2, 3, 4, 5} for k in res.day_status)


def test_sample_fixture_no_false_positive_from_non_targets(sample_text):
    msgs = _sample_messages(sample_text)
    res = analyze(msgs, {1, 2, 3, 4, 5}, [Coverage(dt(26, 0), dt(28, 4))])
    assert all(s.member_id in {1, 2, 3, 4, 5} for s in res.sessions)


def _snapshot(res):
    return (
        sorted((s.key, s.status.value, str(s.prayer_date), str(s.date_source)) for s in res.sessions),
        sorted((r.key, r.review_type.value) for r in res.reviews),
        sorted((k, v.value) for k, v in res.day_status.items()),
        sorted((k, e.event_type.value) for k, e in res.events.items()),
    )


def test_determinism_shuffled_input(sample_text):
    msgs = _sample_messages(sample_text)
    c = [Coverage(dt(26, 0), dt(28, 4))]
    base = _snapshot(analyze(msgs, {1, 2, 3, 4, 5}, c))
    rng = random.Random(7)
    for _ in range(5):
        shuffled = msgs[:]
        rng.shuffle(shuffled)
        assert _snapshot(analyze(shuffled, {1, 2, 3, 4, 5}, c)) == base


def test_same_minute_messages_ordered_by_seq():
    a, b = msg(START, 26, 22, 0, seq=0), msg(END, 26, 22, 0, seq=1)

    res = run([b, a])
    assert not completes(res)
    assert any(r.review_type == ReviewType.AMBIGUOUS for r in res.reviews)


def test_tc13_false_positives_produce_no_sessions():
    texts = ["오늘 기도회 누구니?", "기도해주셔서 감사합니다",
             "기도 시작-마침 안 올리는 사람 체크해줘", "내일을 위해 기도 부탁드립니다"]
    res = run([msg(t, 26, 20 + i) for i, t in enumerate(texts)])
    assert res.sessions == []
    assert res.day_status[(1, D26)] == DayStatus.MISSING


def test_non_target_member_ignored():
    res = run([msg(START, 26, 22, member=9), msg(END, 26, 22, 30, member=9)])
    assert res.sessions == [] and (9, D26) not in res.day_status


def test_one_status_per_member_day():
    res = run([msg(START, 26, 22, 0), msg(END, 26, 22, 30), msg(START, 26, 23, 0), msg(END, 26, 23, 30)])
    assert res.day_status[(1, D26)] == DayStatus.COMPLETE
    assert [k for k in res.day_status if k[1] == D26] == [(1, D26)]


def test_uncovered_day_is_pending_data_not_missing():
    cv = [Coverage(dt(26, 0), dt(26, 23, 59)), Coverage(dt(28, 0), dt(28, 23, 59))]
    res = analyze([], {1}, cv)
    assert res.day_status[(1, D27)] == DayStatus.PENDING_DATA
    assert res.day_status[(1, D26)] != DayStatus.COMPLETE


def test_review_status_decision_persists():
    a, b = msg("무튼 기도합니다", 26, 22, 56), msg(END, 26, 23, 26)
    res = run([a, b])
    key = res.reviews[0].key
    res2 = run([a, b], decisions=AdminDecisions(review_status={key: "HELD"}))
    assert res2.reviews[0].status == "HELD"


def test_admin_date_override():
    a, b = msg(START, 28, 3, 0), msg(END, 28, 3, 30)
    res = run([a, b], last_day=28, decisions=AdminDecisions(date_overrides={a.id: D26}))
    assert res.sessions[0].prayer_date == D26 and res.sessions[0].date_source == DateSource.ADMIN


# --- 평가에서 발견된 사례 ---------------------------------------------------
def test_restart_uses_restart_point_and_abandons_first_start():
    """결정 #4: '다시 기도 시작합니다'는 앞선 시작을 중단으로 보고 재시작 지점부터 세션을 만든다."""
    a = msg("기도시작합니다", 26, 7, 44)
    b = msg("기도 다시 시작합니다", 26, 9, 4)
    c = msg("기도 마칩니다", 26, 9, 36)
    res = run([a, b, c])
    done = completes(res)
    assert len(done) == 1 and done[0].start_message_id == b.id and done[0].duration_seconds == 32 * 60
    first = [s for s in res.sessions if s.start_message_id == a.id][0]
    assert first.status == SessionStatus.INCOMPLETE
    assert not [r for r in res.reviews if r.review_type == ReviewType.DUPLICATE_START]
    assert res.day_status[(1, date(2026, 10, 26))] == DayStatus.COMPLETE


def test_restart_without_open_session_is_plain_start():
    a = msg("다시 기도 시작합니다!", 26, 22, 39)
    b = msg("기도 마쳤습니다!", 26, 23, 10)
    assert len(completes(run([a, b]))) == 1


def test_suffix_start_auto_confirmed_when_idle():
    a = msg("감사한 마음을 가지고 기도 시작합니다!", 26, 21, 0)
    b = msg("기도 마칩니다", 26, 21, 30)
    done = completes(run([a, b]))
    assert len(done) == 1 and done[0].start_message_id == a.id


def test_suffix_start_goes_to_review_when_setting_off():
    a = msg("감사한 마음을 가지고 기도 시작합니다!", 26, 21, 0)
    b = msg("기도 마칩니다", 26, 21, 30)
    res = run([a, b], settings=Settings(auto_confirm_suffix_in_context=False))
    assert not completes(res)
    assert any(r.review_type == ReviewType.MISSING_START and a.id in r.message_ids for r in res.reviews)


def test_emoticon_end_completes_session():
    a = msg("기도 시작합니다!", 26, 19, 35)
    b = msg("기도 마쳤습니다!(강아지)", 26, 20, 10)
    assert len(completes(run([a, b]))) == 1


def test_polite_end_completes_session():
    """2026-10-30 23:29 '기도 시작합니다' → 23:59 '기도 마쳤어요'가 미인증으로 처리되던 버그."""
    a = msg("기도 시작합니다", 26, 23, 29)
    b = msg("기도 마쳤어요", 26, 23, 59)
    res = run([a, b])
    assert len(completes(res)) == 1 and completes(res)[0].duration_seconds == 30 * 60
    assert res.day_status[(1, date(2026, 10, 26))] == DayStatus.COMPLETE
