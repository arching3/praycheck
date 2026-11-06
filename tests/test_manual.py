"""관리자 수동 기록 CRUD: 원본 메시지 없이 완료 세션으로 집계된다."""
from datetime import date, datetime

import pytest

from conftest import cov, dt, msg
from prayer_tracker.engine import AdminDecisions, analyze
from prayer_tracker.models import DateSource, DayStatus, ManualRecord, SessionStatus
from prayer_tracker.reports.day_report import day_report_data
from prayer_tracker.reports.summary import session_details
from prayer_tracker.service import PrayerService

D26, D27 = date(2026, 10, 26), date(2026, 10, 27)


def rec(i=1, member=1, d=D26, s=(22, 0), e=(22, 30), day_offset=0):
    base = datetime(d.year, d.month, d.day + day_offset)
    return ManualRecord(i, member, d, base.replace(hour=s[0], minute=s[1]), base.replace(hour=e[0], minute=e[1]))


# ---- 엔진 --------------------------------------------------------------------
def test_manual_record_counts_as_complete_without_messages():
    res = analyze([], {1}, [cov(26, 27, 4, 0)], AdminDecisions(manual_records=[rec()]))
    s = [x for x in res.sessions if x.manual_id == 1][0]
    assert s.status == SessionStatus.COMPLETE and s.duration_seconds == 30 * 60
    assert s.prayer_date == D26 and s.date_source == DateSource.ADMIN
    assert res.day_status[(1, D26)] == DayStatus.COMPLETE


def test_manual_record_for_non_target_is_ignored():
    res = analyze([], {1}, [cov(26, 27, 4, 0)], AdminDecisions(manual_records=[rec(member=2)]))
    assert not res.sessions


def test_manual_record_affects_dynamic_attribution_of_early_session():
    """26일에 수동 완료 기록이 있으면, 27일 02:00 시작 세션은 26일이 아니라 27일로 귀속된다."""
    a, b = msg("기도 시작합니다", 27, 2, 0), msg("기도 마칩니다", 27, 2, 30)
    without = analyze([a, b], {1}, [cov(26, 28, 4, 0)])
    assert [s.prayer_date for s in without.sessions] == [D26]
    with_manual = analyze([a, b], {1}, [cov(26, 28, 4, 0)], AdminDecisions(manual_records=[rec()]))
    auto = [s for s in with_manual.sessions if s.manual_id is None][0]
    assert auto.prayer_date == D27 and auto.date_source == DateSource.SAME_DAY


def test_manual_record_turns_incomplete_day_complete():
    a = msg("기도 시작합니다", 26, 21, 0)   # 종료 없음 → 미완료
    res = analyze([a], {1}, [cov(26, 27, 4, 0)], AdminDecisions(manual_records=[rec()]))
    assert res.day_status[(1, D26)] == DayStatus.COMPLETE


# ---- 서비스 CRUD -------------------------------------------------------------
EXPORT = """저장한 날짜 : 2026-10-28 09:00:00
--------------- 2026년 10월 26일 월요일 ---------------
[참여자A] [오후 9:00] 안녕하세요
--------------- 2026년 10월 27일 화요일 ---------------
[참여자A] [오후 9:00] 안녕하세요
""".encode("utf-8")


@pytest.fixture
def svc():
    s = PrayerService(":memory:")
    s.save_settings(s.get_settings().model_copy(update={"tracking_start_date": D26}))
    s.import_file("a.txt", EXPORT)
    s.set_targets({m["id"] for m in s.members()})
    return s


def member(svc):
    return svc.members()[0]["id"]


def test_create_read(svc):
    m = member(svc)
    assert svc.result.day_status[(m, D26)] == DayStatus.MISSING
    rid = svc.create_manual_record(m, D26, dt(26, 22), dt(26, 22, 40), "전화로 확인")
    [r] = svc.manual_records()
    assert (r.id, r.member_id, r.prayer_date, r.note) == (rid, m, D26, "전화로 확인")
    assert svc.manual_records(member_id=m + 99) == []
    assert svc.result.day_status[(m, D26)] == DayStatus.COMPLETE
    assert svc.audit_log()[0]["action"] == "create"


def test_update_moves_record_to_another_day(svc):
    m = member(svc)
    rid = svc.create_manual_record(m, D26, dt(26, 22), dt(26, 22, 30))
    svc.update_manual_record(rid, m, D27, dt(27, 21), dt(27, 21, 45), "날짜 정정")
    [r] = svc.manual_records()
    assert r.prayer_date == D27 and r.end_at == dt(27, 21, 45) and r.note == "날짜 정정"
    assert svc.result.day_status[(m, D26)] == DayStatus.MISSING
    assert svc.result.day_status[(m, D27)] == DayStatus.COMPLETE
    log = svc.audit_log()[0]
    assert log["action"] == "update" and "2026-10-26" in log["previous_value"] and "2026-10-27" in log["new_value"]


def test_delete_returns_record_for_undo(svc):
    m = member(svc)
    rid = svc.create_manual_record(m, D26, dt(26, 22), dt(26, 22, 30))
    prev = svc.delete_manual_record(rid)
    assert prev["id"] == rid and svc.manual_records() == []
    assert svc.result.day_status[(m, D26)] == DayStatus.MISSING
    assert svc.delete_manual_record(rid) is None
    assert svc.audit_log()[0]["action"] == "delete"


@pytest.mark.parametrize("start,end,msg_part", [
    (dt(26, 22), dt(26, 22), "늦어야"),
    (dt(26, 22), dt(26, 21), "늦어야"),
    (dt(26, 1), dt(27, 2), "24시간"),
    (dt(29, 22), dt(29, 23), "전날"),
])
def test_validation(svc, start, end, msg_part):
    with pytest.raises(ValueError, match=msg_part):
        svc.create_manual_record(member(svc), D26, start, end)
    assert svc.manual_records() == []


def test_update_missing_record_raises(svc):
    with pytest.raises(KeyError):
        svc.update_manual_record(999, member(svc), D26, dt(26, 22), dt(26, 22, 30))


def test_delete_all_data_removes_manual_records(svc):
    svc.create_manual_record(member(svc), D26, dt(26, 22), dt(26, 22, 30))
    svc.delete_all_data()
    assert svc.manual_records() == []


# ---- 보고서 -------------------------------------------------------------------
def test_reports_mark_manual_records(svc):
    m = member(svc)
    svc.create_manual_record(m, D26, dt(26, 22), dt(26, 22, 30))
    [row] = session_details(svc, D26, D26)
    assert row["입력 방식"] == "수동 기록" and row["기도 시간"] == "30분"
    line = day_report_data(svc, D26).rows[0].sessions[0]
    assert line.manual and (line.start, line.end, line.duration) == ("22:00", "22:30", "30분")
