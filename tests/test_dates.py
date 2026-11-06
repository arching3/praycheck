from datetime import date

from conftest import cov, dt
from prayer_tracker.assignment.dates import assign_member, is_covered, merge_coverage
from prayer_tracker.models import Coverage, DateSource, ReviewType, Session, SessionStatus

MON, TUE, WED = 26, 27, 28
MON_D = date(2026, 10, 26)


def sess(start, end=None, mid="s", status=SessionStatus.COMPLETE):
    return Session(1, mid, mid + "e", start, end, status)


def assign(sessions, tracking_start=MON_D, grace=4, overrides=None):
    return assign_member(sessions, merge_coverage([cov(26, 28)]), tracking_start, grace, overrides or {})


def test_merge_coverage_overlapping_and_disjoint():
    merged = merge_coverage([cov(26, 27), cov(27, 28), Coverage(dt(30, 0), dt(30, 5))])
    assert len(merged) == 2 and merged[0].end == dt(28, 23, 59)


def test_is_covered():
    c = merge_coverage([cov(26, 27)])
    assert is_covered(c, dt(26, 4), dt(27, 3))
    assert not is_covered(c, dt(25, 4), dt(26, 3))


def test_tc07_midnight_cross_belongs_to_start_day():
    s = sess(dt(TUE, 23, 45), dt(WED, 0, 19))
    assign([s])
    assert s.prayer_date == date(2026, 10, 27) and s.date_source == DateSource.START_DATE
    assert (s.start_at, s.end_at) == (dt(TUE, 23, 45), dt(WED, 0, 19))


def test_tc08_dawn_goes_to_previous_day_when_it_is_uncertified():
    s = sess(dt(WED, 3, 0), dt(WED, 3, 30))
    assign([s])
    assert s.prayer_date == date(2026, 10, 27) and s.date_source == DateSource.PREV_DAY


def test_tc08_dawn_goes_to_same_day_when_previous_complete():
    prev = sess(dt(TUE, 22, 0), dt(TUE, 22, 30), "p")
    s = sess(dt(WED, 3, 0), dt(WED, 3, 30))
    assign([prev, s])
    assert s.prayer_date == date(2026, 10, 28) and s.date_source == DateSource.SAME_DAY


def test_dawn_with_previous_open_session_is_pending_review():
    prev = sess(dt(TUE, 22, 0), None, "p", SessionStatus.INCOMPLETE)
    s = sess(dt(WED, 3, 0), dt(WED, 3, 30))
    reviews = assign([prev, s])
    assert s.date_source == DateSource.PENDING and s.prayer_date is None
    assert reviews[0].review_type == ReviewType.DATE_ASSIGNMENT


def test_tc09_0400_boundary_is_same_day_regardless():
    s = sess(dt(WED, 4, 0), dt(WED, 4, 30))
    assign([s])
    assert s.prayer_date == date(2026, 10, 28) and s.date_source == DateSource.START_DATE


def test_0359_to_0430_uses_dawn_rule_by_start_time():
    s = sess(dt(WED, 3, 59), dt(WED, 4, 30))
    assign([s])
    assert s.date_source == DateSource.PREV_DAY and s.prayer_date == date(2026, 10, 27)


def test_tc10_first_day_dawn_is_out_of_range():
    s = sess(dt(MON, 0, 13), dt(MON, 0, 43))
    reviews = assign([s])
    assert s.date_source == DateSource.OUT_OF_RANGE
    assert s.prayer_date == date(2026, 10, 25)
    assert reviews == []


def test_earlier_tracking_start_with_uncovered_prev_day_needs_date_review():
    s = sess(dt(MON, 0, 13), dt(MON, 0, 43))
    reviews = assign([s], tracking_start=date(2026, 10, 25))
    assert s.date_source == DateSource.PENDING and s.prayer_date is None
    assert reviews[0].review_type == ReviewType.DATE_ASSIGNMENT
    assert reviews[0].target_date == date(2026, 10, 25)


def test_admin_override_wins():
    s = sess(dt(WED, 3, 0), dt(WED, 3, 30), "x")
    assign([s], overrides={"x": MON_D})
    assert s.prayer_date == MON_D and s.date_source == DateSource.ADMIN


def test_custom_grace_hour():
    s = sess(dt(WED, 4, 30), dt(WED, 5, 0))
    assign([s], grace=6)
    assert s.date_source == DateSource.PREV_DAY
