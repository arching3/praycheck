"""Windows 카카오톡 TXT 내보내기 파서. UI·DB와 독립적이다."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

from prayer_tracker.models import Message, MessageType

DATE_LINE = re.compile(r"^-+\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*\S*요일\s*-+\s*$")
# 성경 구절 "[요한복음 7:37-41]"과 구분하기 위해 두 번째 대괄호에 오전/오후 시각을 요구한다.
HEADER = re.compile(r"^\[(?P<name>[^\]]+)\] \[(?P<ampm>오전|오후) (?P<h>\d{1,2}):(?P<m>\d{2})\] ?(?P<body>.*)$")

MEDIA_PATTERNS = [
    re.compile(r"^사진( \d+장)?$"),
    re.compile(r"^동영상( \d+개)?$"),
    re.compile(r"^이모티콘$"),
    re.compile(r"^파일: .+"),
    re.compile(r"^음성메시지"),
    re.compile(r"^(투표|일정|공지)\s*[:：]?"),
    re.compile(r"^샵검색\s*[:：]"),
    re.compile(r"^톡게시판 "),
]
DELETED_TEXT = "메시지가 삭제되었습니다."
# 내보내기 파일 머리: "🌟 님과 카카오톡 대화" / "저장한 날짜 : 2026-10-31 00:37:48"
SAVED_AT = re.compile(r"^저장한 날짜\s*:\s*(\d{4})-(\d{1,2})-(\d{1,2}) (\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")
TITLE = re.compile(r"카카오톡 대화\s*$")
SYSTEM_PATTERNS = [
    re.compile(r"님이 (들어왔습니다|나갔습니다|.+님을 초대했습니다)"),
    re.compile(r"^채팅방 관리자가"),
]


@dataclass
class ParseIssue:
    line_no: int
    text: str
    reason: str


@dataclass
class ParseResult:
    messages: list[Message] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    first_date: date | None = None
    last_message_at: datetime | None = None
    encoding: str = "utf-8"
    deleted_notices: int = 0
    saved_at: datetime | None = None   # 내보내기 시각 = 수집 범위의 끝


def decode_bytes(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-16", "cp949"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and not data[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return text, enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8(replace)"


def to_24h(ampm: str, h: int) -> int:
    if ampm == "오전":
        return 0 if h == 12 else h
    return 12 if h == 12 else h + 12


def classify_type(body: str) -> MessageType:
    b = body.strip()
    if b == DELETED_TEXT:
        return MessageType.DELETED
    if any(p.search(b) for p in MEDIA_PATTERNS):
        return MessageType.MEDIA
    return MessageType.TEXT


def make_dedup_key(sender: str, sent_at: datetime, text: str, occurrence: int) -> str:
    """서버 메시지 ID가 없으므로 (발신자, 분, 본문, 같은 분·같은 본문 내 순번)으로 식별한다.
    한계: 파일 경계가 한 분의 중간을 자르면 순번이 어긋날 수 있다."""
    raw = f"{sender}\x1f{sent_at:%Y-%m-%d %H:%M}\x1f{text}\x1f{occurrence}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def parse_text(text: str) -> ParseResult:
    result = ParseResult()
    current_date: date | None = None
    cur: dict | None = None
    drafts: list[dict] = []

    def flush():
        nonlocal cur
        if cur is not None:
            cur["body"] = "\n".join(cur["lines"]).rstrip("\n")
            drafts.append(cur)
            cur = None

    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.rstrip("\r")
        m = DATE_LINE.match(line.strip())
        if m:
            flush()
            current_date = date(int(m[1]), int(m[2]), int(m[3]))
            if result.first_date is None:
                result.first_date = current_date
            continue
        h = HEADER.match(line)
        if h:
            flush()
            if current_date is None:
                result.issues.append(ParseIssue(line_no, line, "날짜 구분선 이전의 메시지"))
                continue
            hour = to_24h(h["ampm"], int(h["h"]))
            sent_at = datetime(current_date.year, current_date.month, current_date.day, hour, int(h["m"]))
            cur = {"sender": h["name"].strip(), "sent_at": sent_at, "lines": [h["body"]], "line_no": line_no}
            continue
        if current_date is None and cur is None:
            sm = SAVED_AT.match(line.strip())
            if sm:
                result.saved_at = datetime(*(int(x) for x in sm.groups()[:5]), int(sm[6] or 0))
                continue
            if TITLE.search(line):
                continue
        if line.strip() == DELETED_TEXT:
            # 헤더 없는 삭제 알림은 앞 메시지의 본문이 아니다(평가에서 8건 발견)
            result.deleted_notices += 1
            continue
        if cur is not None:
            cur["lines"].append(line)
        elif line.strip():
            # 시스템 메시지(입장/퇴장, 헤더 없는 삭제 알림 등)는 헤더 없이 한 줄로 나온다.
            if any(p.search(line) for p in SYSTEM_PATTERNS):
                continue
            result.issues.append(ParseIssue(line_no, line, "헤더 없는 줄(메시지에 연결 불가)"))
    flush()

    occ: Counter = Counter()
    minute_seq: Counter = Counter()
    for d in drafts:
        body = d["body"]
        k = (d["sender"], d["sent_at"], body)
        occurrence = occ[k]
        occ[k] += 1
        seq = minute_seq[d["sent_at"]]
        minute_seq[d["sent_at"]] += 1
        result.messages.append(Message(
            id=make_dedup_key(d["sender"], d["sent_at"], body, occurrence),
            sender_raw=d["sender"],
            sent_at=d["sent_at"],
            raw_text=body,
            message_type=classify_type(body),
            source_position=d["line_no"],
            seq=seq,
        ))
    if result.messages:
        result.last_message_at = max(m.sent_at for m in result.messages)
    return result


def parse_bytes(data: bytes) -> ParseResult:
    text, enc = decode_bytes(data)
    res = parse_text(text)
    res.encoding = enc
    return res


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
