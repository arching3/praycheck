"""도메인 모델. 원본(Message)과 파생 결과(Event/Session/Review/DayStatus)를 분리한다."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class MessageType(str, Enum):
    TEXT = "TEXT"
    MEDIA = "MEDIA"
    SYSTEM = "SYSTEM"
    DELETED = "DELETED"


class EventType(str, Enum):
    START = "START"
    END = "END"
    OTHER = "OTHER"
    AMBIGUOUS = "AMBIGUOUS"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ClassificationSource(str, Enum):
    RULE = "RULE"          # 명확한 규칙
    TYPO = "TYPO"          # 검증된 오타/구어체 규칙
    CONTEXT = "CONTEXT"    # 문맥(진행 중 세션)으로 확정
    ADMIN = "ADMIN"        # 관리자 지정


class SessionStatus(str, Enum):
    COMPLETE = "COMPLETE"
    IN_PROGRESS = "IN_PROGRESS"   # 종료 대기 (데이터가 아직 끝나지 않음)
    INCOMPLETE = "INCOMPLETE"     # 종료 누락 확정


class DateSource(str, Enum):
    START_DATE = "START_DATE"           # 04:00 이후 시작 → 시작일
    PREV_DAY = "PREV_DAY"               # 새벽 시작, 전날 미인증 → 전날
    SAME_DAY = "SAME_DAY"               # 새벽 시작, 전날 완료 → 당일
    ADMIN = "ADMIN"
    PENDING = "PENDING"                 # 판단 불가 → 검토
    OUT_OF_RANGE = "OUT_OF_RANGE"       # 추적 시작일 이전으로 귀속 → 집계 제외


class DayStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    MISSING = "MISSING"
    PENDING_REVIEW = "PENDING_REVIEW"
    PENDING_DATA = "PENDING_DATA"


class ReviewType(str, Enum):
    MISSING_START = "MISSING_START"         # END만 있음
    MISSING_END = "MISSING_END"             # START만 있음
    DUPLICATE_START = "DUPLICATE_START"
    DUPLICATE_END = "DUPLICATE_END"
    AMBIGUOUS = "AMBIGUOUS"                 # 의미 불확실 후보
    DATE_ASSIGNMENT = "DATE_ASSIGNMENT"     # 날짜 귀속 판단 불가
    DUPLICATE_MESSAGE = "DUPLICATE_MESSAGE"


@dataclass
class Message:
    id: str                    # deduplication_key (업로드 순서와 무관한 결정적 ID)
    sender_raw: str
    sent_at: datetime          # KST naive
    raw_text: str
    message_type: MessageType
    source_file_id: int | None = None
    source_position: int = 0   # 파일 내 줄 번호
    seq: int = 0               # 같은 분 안의 순서
    member_id: int | None = None
    parse_status: str = "OK"

    @property
    def sort_key(self):
        return (self.sent_at, self.seq, self.id)


@dataclass
class Event:
    message_id: str
    event_type: EventType
    confidence: Confidence
    source: ClassificationSource
    matched_rule: str = ""
    candidate: EventType | None = None   # AMBIGUOUS일 때 가능한 유형
    normalized_text: str = ""


@dataclass
class Session:
    member_id: int
    start_message_id: str | None
    end_message_id: str | None
    start_at: datetime | None
    end_at: datetime | None
    status: SessionStatus
    prayer_date: date | None = None
    date_source: DateSource | None = None
    manual: bool = False                 # 관리자가 메시지를 직접 연결한 세션
    manual_id: int | None = None         # 관리자가 직접 입력한 수동 기록(메시지 없음)

    @property
    def duration_seconds(self) -> int | None:
        if self.start_at and self.end_at and self.status == SessionStatus.COMPLETE:
            return int((self.end_at - self.start_at).total_seconds())
        return None

    @property
    def key(self) -> str:
        if self.manual_id is not None:
            return f"{self.member_id}:manual:{self.manual_id}"
        return f"{self.member_id}:{self.start_message_id}:{self.end_message_id}"


@dataclass
class ManualRecord:
    """관리자가 직접 입력한 기도 기록. 원본 메시지 없이 완료 세션으로 집계된다."""
    id: int
    member_id: int
    prayer_date: date        # 인증 귀속 날짜(관리자 지정)
    start_at: datetime
    end_at: datetime
    note: str = ""


@dataclass
class Review:
    review_type: ReviewType
    member_id: int | None
    target_date: date | None
    message_ids: list[str]
    reason: str
    session_key: str | None = None
    status: str = "OPEN"   # OPEN / RESOLVED / HELD / NO_CANDIDATE

    @property
    def key(self) -> str:
        """재계산 후에도 같은 문제면 같은 키 → 관리자 결정(보류/해결)이 유지된다."""
        return f"{self.review_type.value}:{self.member_id}:{','.join(sorted(self.message_ids))}"


@dataclass
class Coverage:
    """수집된 데이터가 덮는 구간 [start, end]. start는 파일의 첫 날짜 구분선 00:00."""
    start: datetime
    end: datetime


@dataclass
class AnalysisResult:
    events: dict[str, Event] = field(default_factory=dict)
    sessions: list[Session] = field(default_factory=list)
    reviews: list[Review] = field(default_factory=list)
    day_status: dict[tuple[int, date], DayStatus] = field(default_factory=dict)
