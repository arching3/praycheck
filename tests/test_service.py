"""전체 기간 내보내기 업로드 흐름: 추적 시작일 필수, 저장 범위 제한, 내보내기 시각, 재업로드."""
from datetime import date, datetime

from prayer_tracker.service import PrayerService

EXPORT = """🌟 님과 카카오톡 대화
저장한 날짜 : 2026-10-28 00:30:15

--------------- 2026년 10월 24일 토요일 ---------------
[참여자A] [오후 10:00] 아주 예전 대화
--------------- 2026년 10월 25일 일요일 ---------------
[참여자A] [오후 10:00] 기도 시작합니다
[참여자A] [오후 10:30] 기도 마칩니다
--------------- 2026년 10월 26일 월요일 ---------------
[참여자A] [오후 10:00] 기도 시작합니다
[참여자A] [오후 10:30] 기도 마쳤습니다!(별똥별)
--------------- 2026년 10월 27일 화요일 ---------------
[참여자A] [오후 9:00] 기도 시작합니다
[참여자A] [오후 9:30] 기도 마칩니다
""".encode("utf-8")


def make(start: date | None) -> PrayerService:
    svc = PrayerService(":memory:")
    if start:
        svc.save_settings(svc.get_settings().model_copy(update={"tracking_start_date": start}))
    return svc


def test_upload_requires_tracking_start_date():
    svc = make(None)
    assert svc.import_file("a.txt", EXPORT).status == "NEED_START_DATE"
    assert not svc.load_messages()


def test_only_messages_from_day_before_start_are_stored():
    svc = make(date(2026, 10, 26))
    rep = svc.import_file("a.txt", EXPORT)
    assert rep.status == "OK" and rep.skipped_before_start == 1   # 10/24 대화는 저장 안 함
    assert min(m.sent_at for m in svc.load_messages()) == datetime(2026, 10, 25, 22, 0)
    assert not rep.issues   # 제목·저장한 날짜 줄은 경고가 아니다


def test_saved_at_header_is_coverage_end():
    svc = make(date(2026, 10, 26))
    svc.import_file("a.txt", EXPORT)
    cov = svc.coverage()[0]
    assert cov.start == datetime(2026, 10, 25) and cov.end == datetime(2026, 10, 28, 0, 30, 15)


def test_days_before_start_not_counted_and_emoticon_end_completes():
    svc = make(date(2026, 10, 26))
    svc.import_file("a.txt", EXPORT)
    svc.set_targets({m["id"] for m in svc.members()})
    days = {d for (_, d) in svc.result.day_status}
    assert min(days) == date(2026, 10, 26)
    assert svc.result.day_status[(svc.members()[0]["id"], date(2026, 10, 26))].value == "COMPLETE"


def test_same_file_again_is_duplicate():
    svc = make(date(2026, 10, 26))
    svc.import_file("a.txt", EXPORT)
    assert svc.import_file("a.txt", EXPORT).status == "DUPLICATE_FILE"


def test_moving_start_earlier_then_reupload_fills_gap():
    svc = make(date(2026, 10, 26))
    svc.import_file("a.txt", EXPORT)
    n = len(svc.load_messages())
    svc.save_settings(svc.get_settings().model_copy(update={"tracking_start_date": date(2026, 10, 25)}))
    rep = svc.import_file("a.txt", EXPORT)
    assert rep.status == "OK" and rep.new_messages == 1 and len(svc.source_files()) == 1
    assert len(svc.load_messages()) == n + 1


def test_moving_start_later_then_purge():
    svc = make(date(2026, 10, 26))
    svc.import_file("a.txt", EXPORT)
    svc.save_settings(svc.get_settings().model_copy(update={"tracking_start_date": date(2026, 10, 27)}))
    assert svc.count_before_cutoff() == 2
    assert svc.purge_before_cutoff() == 2 and svc.count_before_cutoff() == 0
    assert svc.audit_log()[0]["action"] == "purge"


def test_newer_full_export_adds_only_new_messages():
    svc = make(date(2026, 10, 26))
    svc.import_file("a.txt", EXPORT)
    newer = EXPORT.replace(b"00:30:15", b"23:00:00") + "[참여자A] [오후 10:00] 기도 시작합니다\n".encode()
    rep = svc.import_file("b.txt", newer)
    assert rep.status == "OK" and rep.new_messages == 1
