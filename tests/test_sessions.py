from conftest import dt, msg
from prayer_tracker.classification.classifier import classify_message
from prayer_tracker.config import Settings
from prayer_tracker.models import ReviewType, SessionStatus
from prayer_tracker.sessions.matcher import match_member

S = Settings()
START, END = "기도 시작합니다", "기도 마칩니다"


def run(msgs, cov_end=dt(30, 23, 59), settings=S, links=()):
    items = [(m, classify_message(m, settings)) for m in sorted(msgs, key=lambda m: m.sort_key)]
    return match_member(1, items, cov_end, settings, list(links))


def test_simple_session_30_minutes():
    sessions, reviews, _ = run([msg(START, 26, 22, 19), msg(END, 26, 22, 49)])
    assert len(sessions) == 1 and not reviews
    s = sessions[0]
    assert s.status == SessionStatus.COMPLETE and s.duration_seconds == 1800


def test_session_spans_midnight_keeps_real_times():
    sessions, _, _ = run([msg(START, 27, 23, 45), msg(END, 28, 0, 19)])
    s = sessions[0]
    assert s.start_at == dt(27, 23, 45) and s.end_at == dt(28, 0, 19)
    assert s.status == SessionStatus.COMPLETE


def test_bare_end_in_open_session_auto_confirmed():
    sessions, reviews, updated = run([msg(START, 26, 22), msg("마칩니다", 26, 22, 30)])
    assert sessions[0].status == SessionStatus.COMPLETE
    assert not reviews and updated


def test_bare_end_not_auto_confirmed_when_setting_off():
    sessions, reviews, _ = run([msg(START, 26, 22), msg("마칩니다", 26, 22, 30)],
                               settings=Settings(auto_confirm_bare_end_in_session=False))
    assert sessions[0].status != SessionStatus.COMPLETE
    assert reviews


def test_bare_end_without_session_creates_no_session():
    sessions, reviews, _ = run([msg("마칩니다", 26, 22)])
    assert sessions == []
    assert [r.review_type for r in reviews] == [ReviewType.AMBIGUOUS]


def test_typo_end_in_open_session_auto_confirmed():
    sessions, _, _ = run([msg(START, 26, 22, 19), msg("ㄱ도 마칩니다", 26, 22, 49)])
    assert sessions[0].status == SessionStatus.COMPLETE and sessions[0].duration_seconds == 1800


def test_end_only_raises_missing_start():
    sessions, reviews, _ = run([msg(END, 26, 22)])
    assert sessions == []
    assert reviews[0].review_type == ReviewType.MISSING_START


def test_loose_start_not_a_session_but_listed_as_candidate_for_end():
    m1, m2 = msg("무튼 기도합니다", 26, 22, 56), msg(END, 26, 23, 26)
    sessions, reviews, _ = run([m1, m2])
    assert sessions == []
    r = reviews[0]
    assert r.review_type == ReviewType.MISSING_START and m1.id in r.message_ids


def test_start_without_end_is_in_progress_when_data_recent():
    sessions, reviews, _ = run([msg(START, 26, 22, 30)], cov_end=dt(26, 23, 59))
    assert sessions[0].status == SessionStatus.IN_PROGRESS


def test_tc11_start_without_end_incomplete_no_times_no_review():
    sessions, reviews, _ = run([msg(START, 26, 22, 30)], cov_end=dt(30, 23, 59))
    s = sessions[0]
    assert s.status == SessionStatus.INCOMPLETE
    assert s.end_at is None and s.duration_seconds is None
    assert reviews == []


def test_incomplete_with_end_candidate_raises_missing_end():
    m = msg("마쳤습니다아", 26, 23)  # 구어체 후보
    sessions, reviews, _ = run([msg(START, 26, 22, 30), m], cov_end=dt(30, 23, 59),
                               settings=Settings(auto_confirm_bare_end_in_session=False))
    assert sessions[0].status == SessionStatus.INCOMPLETE
    assert [r.review_type for r in reviews] == [ReviewType.MISSING_END]


def test_end_after_too_long_gap_not_matched():
    sessions, reviews, _ = run([msg(START, 26, 10), msg(END, 26, 20)])
    assert sessions[0].status == SessionStatus.INCOMPLETE
    assert any(r.review_type == ReviewType.MISSING_START for r in reviews)


def test_duplicate_start_review():
    _, reviews, _ = run([msg(START, 26, 22, 0), msg(START, 26, 22, 5), msg(END, 26, 22, 30)])
    assert ReviewType.DUPLICATE_START in {r.review_type for r in reviews}


def test_duplicate_end_review():
    _, reviews, _ = run([msg(START, 26, 22, 0), msg(END, 26, 22, 30), msg(END, 26, 22, 35)])
    assert ReviewType.DUPLICATE_END in {r.review_type for r in reviews}


def test_manual_link_creates_complete_session():
    a, b = msg("무튼 기도합니다", 26, 22, 56), msg(END, 26, 23, 26)
    sessions, _, _ = run([a, b], links=[(a.id, b.id)])
    assert len(sessions) == 1 and sessions[0].manual
    assert sessions[0].duration_seconds == 1800
