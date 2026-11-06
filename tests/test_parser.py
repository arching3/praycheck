from datetime import date, datetime

from prayer_tracker.ingestion.parser import parse_bytes, parse_text
from prayer_tracker.models import MessageType


def by_text(res, needle):
    return [m for m in res.messages if needle in m.raw_text]


def test_basic_fields(sample_text):
    res = parse_text(sample_text)
    assert res.first_date == date(2026, 10, 26)
    first = res.messages[0]
    assert first.sender_raw == "참여자A"
    assert first.sent_at == datetime(2026, 10, 26, 0, 13)  # 오전 12시 = 0시
    assert first.raw_text == "기도 시작합니다"
    assert first.message_type == MessageType.TEXT


def test_pm_conversion(sample_text):
    res = parse_text(sample_text)
    m = by_text(res, "무튼")[0]
    assert m.sent_at == datetime(2026, 10, 26, 22, 56)


def test_noon_and_midnight():
    text = ("--------------- 2026년 10월 26일 월요일 ---------------\n"
            "[참여자A] [오후 12:05] 정오\n[참여자A] [오전 12:05] 자정\n")
    ms = parse_text(text).messages
    assert ms[0].sent_at.hour == 12 and ms[1].sent_at.hour == 0


def test_multiline_message_is_single_message(sample_text):
    res = parse_text(sample_text)
    m = by_text(res, "아주 좋아요")[0]
    assert m.raw_text == "아주 좋아요~~\n기도시작합니다"
    assert m.sender_raw == "참여자C"
    assert len(by_text(res, "기도시작합니다")) == 1 or all(
        "아주" in x.raw_text for x in by_text(res, "기도시작합니다"))


def test_bible_verse_is_not_header(sample_text):
    res = parse_text(sample_text)
    m = by_text(res, "오늘 말씀입니다")[0]
    assert "[요한복음 7:37-41]" in m.raw_text
    assert "37 명절 끝 날" in m.raw_text
    assert not any(x.sender_raw == "요한복음 7:37-41" for x in res.messages)


def test_deleted_message_headerless_not_attached_to_previous(sample_text):
    """헤더 없는 삭제 알림은 앞 메시지 본문에 붙이지 않고 따로 센다."""
    res = parse_text(sample_text)
    m = by_text(res, "기도회")[0]
    assert "메시지가 삭제되었습니다." not in m.raw_text
    assert res.deleted_notices >= 1


def test_deleted_notice_between_lines_of_messages():
    text = ("--------------- 2026년 10월 26일 월요일 ---------------\n"
            "[참여자A] [오후 5:58] 기도 시작합니다\n"
            "메시지가 삭제되었습니다.\n"
            "[참여자A] [오후 6:30] 기도 마칩니다\n")
    res = parse_text(text)
    assert [m.raw_text for m in res.messages] == ["기도 시작합니다", "기도 마칩니다"]
    assert res.deleted_notices == 1 and not res.issues


def test_deleted_message_with_header():
    text = ("--------------- 2026년 10월 26일 월요일 ---------------\n"
            "[참여자A] [오후 1:00] 메시지가 삭제되었습니다.\n")
    assert parse_text(text).messages[0].message_type == MessageType.DELETED


def test_media_types(sample_text):
    res = parse_text(sample_text)
    for needle in ("사진 3장", "이모티콘", "동영상"):
        assert by_text(res, needle)[0].message_type == MessageType.MEDIA


def test_date_divider_changes_date(sample_text):
    res = parse_text(sample_text)
    last = res.messages[-1]
    assert last.sent_at == datetime(2026, 10, 28, 0, 19)
    assert res.last_message_at == max(m.sent_at for m in res.messages)


def test_message_before_date_divider_is_issue():
    res = parse_text("[참여자A] [오후 1:00] 안녕\n")
    assert res.messages == [] and len(res.issues) == 1


def test_crlf_and_bom_bytes(sample_text):
    data = b"\xef\xbb\xbf" + sample_text.replace("\n", "\r\n").encode("utf-8")
    res = parse_bytes(data)
    assert res.messages[0].raw_text == "기도 시작합니다"
    assert len(res.messages) == len(parse_text(sample_text).messages)


def test_cp949_bytes(sample_text):
    res = parse_bytes(sample_text.encode("cp949"))
    assert res.encoding == "cp949"
    assert res.messages[0].sender_raw == "참여자A"


def test_ids_unique_and_deterministic(sample_text):
    a, b = parse_text(sample_text), parse_text(sample_text)
    ids = [m.id for m in a.messages]
    assert len(set(ids)) == len(ids)
    assert ids == [m.id for m in b.messages]


def test_same_minute_same_body_gets_distinct_ids():
    text = ("--------------- 2026년 10월 26일 월요일 ---------------\n"
            "[참여자A] [오후 1:00] ㅋㅋ\n[참여자A] [오후 1:00] ㅋㅋ\n")
    ms = parse_text(text).messages
    assert ms[0].id != ms[1].id and [m.seq for m in ms] == [0, 1]


def test_duplicate_upload_same_ids(sample_text):
    """TC-12 파서 수준: 같은 파일 재파싱 시 id가 동일 → id 기준 병합하면 중복 없음."""
    first = {m.id for m in parse_text(sample_text).messages}
    second = {m.id for m in parse_text(sample_text).messages}
    assert first == second
