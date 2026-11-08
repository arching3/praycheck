"""규칙 기반 인증 분류. 메시지를 줄 단위로 보고, 명확한 인증 표현이 '독립된 줄'로 존재할 때만 인정한다.

출력 규칙:
- HIGH   → event_type = START/END 확정
- MEDIUM → event_type = AMBIGUOUS, candidate 지정 (세션 문맥이 맞으면 matcher가 자동 확정)
- LOW    → event_type = AMBIGUOUS, candidate 지정 (관리자 검토)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from prayer_tracker.config import Settings
from prayer_tracker.models import (
    ClassificationSource, Confidence, Event, EventType, Message, MessageType,
)

# ---- 표현 사전 (확장 가능) -------------------------------------------------
# 시작·종료 동사 어미. 합쇼체(-습니다)와 해요체(-어요/-게요)를 함께 받는다("기도 마쳤어요").
START_VERB = r"시작(합니다|하겠습니다|할게요|할께요|합니다요|해요|했어요|했습니다)"
END_VERB = (r"(마칩니다|마쳤습니다|마치겠습니다|마칠게요|마칠께요|마쳤어요|마쳐요|마침|마치다|"
            r"끝냈습니다|끝냈어요|끝났습니다|끝났어요|끝마쳤습니다|끝마쳤어요|끝마칩니다|끝|"
            r"완료했습니다|완료했어요|완료|완료합니다)")

START_HIGH = [
    # "다시 기도 시작합니다" / "기도 다시 시작합니다"는 재시작(start_restart)으로 구분한다
    ("start_explicit", re.compile(rf"^(다시)?기도(를)?(다시)?(시작|{START_VERB})$")),
    ("start_will_pray", re.compile(r"^기도(를)?하겠습니다$")),
]
END_HIGH = [
    ("end_explicit", re.compile(rf"^기도(를)?{END_VERB}$")),
]
# 문장 끝에 붙은 명시적 인증("감사한 마음을 가지고 기도 시작합니다!") → MEDIUM, 세션 문맥이 맞을 때만 자동 확정.
# "기도하겠습니다"는 요청에 대한 응답일 수 있어 제외한다(TC-05). 단음절 '끝'·'완료'·'마침'은 문장 끝에선 받지 않는다.
SUFFIX_START = ("start_suffix", re.compile(rf"기도(를)?(다시)?{START_VERB}$"))
SUFFIX_END = ("end_suffix", re.compile(
    r"기도(를)?(마칩니다|마쳤습니다|마치겠습니다|마쳤어요|끝냈습니다|끝냈어요|끝마쳤습니다|끝마쳤어요|"
    r"완료했습니다|완료했어요)$"))
SUFFIX_MAX_LEN = 60
SUFFIX_EXCLUDE = re.compile(r"\?|부탁|체크|확인|안\s*올리|해\s*주|누구|기도회|요청")

# 단독 동사: 문맥 없이는 확정 금지 ('끝났어요'처럼 다른 일에도 흔히 쓰는 말은 넣지 않는다)
BARE_END = ("bare_end", re.compile(r"^(마칩니다|마쳤습니다|마치겠습니다|마쳤어요|마침|끝났습니다|끝냈습니다)$"))
BARE_START = ("bare_start", re.compile(r"^(시작합니다|시작하겠습니다|시작할게요|시작)$"))
# 비정형 표현(짧은 문장 안의 기도 동사)
LOOSE_START = ("loose_start", re.compile(r"기도(합니다|할게요|할께요|해요|하겠습니다)$"))
LOOSE_END = ("loose_end", re.compile(r"기도(했어요|했습니다|했어용)$"))
LOOSE_MAX_LEN = 15
# 단독 "기도합니다": 시작 인증으로 자주 쓰지만 기도 요청에 대한 답일 수도 있다 → MEDIUM 후보.
# matcher가 같은 사람의 종료가 뒤따를 때만 시작으로 자동 확정한다(그 외에는 검토).
PRAY_START = ("start_pray_bare", re.compile(r"^기도(합니다|합니다요)$"))

# 일상 대화·요청·응답을 나타내는 단서 → 인증으로 보지 않음
EXCLUDE = re.compile(
    r"기도회|기도해\s*주|기도해줘|부탁|감사|위해|위하여|제목|체크|확인|파이팅|화이팅|요청|"
    r"안\s*올리|기도한다|누구|\?"
)

CANONICAL = {
    "기도시작합니다": EventType.START,
    "기도시작하겠습니다": EventType.START,
    "기도마칩니다": EventType.END,
    "기도마쳤습니다": EventType.END,
}

_CONF_ORDER = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}


@dataclass
class LineResult:
    event_type: EventType          # START / END (후보 포함)
    confidence: Confidence
    source: ClassificationSource
    rule: str
    normalized: str


# ---- 정규화 ---------------------------------------------------------------
_TRAIL = re.compile(r"[\s!~.,·…^_ㅎㅋ♡♥❤😊🙏]+$")
_LEAD = re.compile(r"^[\s\-–—•·*]+")
# 카카오톡 PC 이모티콘 텍스트 표기: "(별똥별)", "(강아지)" 등
_EMO_LEAD = re.compile(r"^\([가-힣A-Za-z]{1,8}\)\s*")
_EMO_TRAIL = re.compile(r"\s*\([가-힣A-Za-z]{1,8}\)$")


def normalize(line: str) -> tuple[str, list[str]]:
    """반환: (정규화된 문장, 적용된 '의미 있는' 오타 규칙 목록).
    공백·문장부호 정리는 오타로 치지 않는다(HIGH 유지)."""
    s = re.sub(r"\s+", " ", line.strip())
    prev = None
    while s != prev:   # "기도 마쳤습니다!(별똥별)" → 이모티콘·문장부호를 번갈아 제거
        prev = s
        s = _EMO_TRAIL.sub("", _EMO_LEAD.sub("", _TRAIL.sub("", _LEAD.sub("", s))))
    typos: list[str] = []
    if "ㄱ도" in s:
        s = s.replace("ㄱ도", "기도"); typos.append("typo_giyeok")
    if re.search(r"(니|어|여)당$", s):
        s = re.sub(r"당$", "다", s); typos.append("colloquial_dang")
    if re.search(r"다[아앙]+$", s):
        s = re.sub(r"다[아앙]+$", "다", s); typos.append("colloquial_da_a")
    if re.search(r"기도\s*끝했", s):         # "기도 끝했어요" → 끝냈어요 (받침 누락)
        s = re.sub(r"끝했", "끝냈", s); typos.append("typo_kkeut")
    if re.search(r"(어|게|께|해)용$", s):   # "마쳤어용", "시작할게용"
        s = re.sub(r"용$", "요", s); typos.append("colloquial_yong")
    return s, typos


def _decompose(s: str) -> str:
    """한글 음절을 자모로 분해 (자모 수준 편집 거리용)."""
    out = []
    for ch in s:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(chr(0x1100 + code // 588))
            out.append(chr(0x1161 + (code % 588) // 28))
            if code % 28:
                out.append(chr(0x11A7 + code % 28))
        else:
            out.append(ch)
    return "".join(out)


def classify_line(line: str, settings: Settings) -> LineResult | None:
    norm, typos = normalize(line)
    compact = norm.replace(" ", "")
    if not compact:
        return None
    excluded = bool(EXCLUDE.search(norm))
    for rules, et in ((START_HIGH, EventType.START), (END_HIGH, EventType.END)):
        if excluded:
            break
        for name, rx in rules:
            if rx.match(compact):
                if et == EventType.START and "다시" in compact:
                    name = "start_restart"
                if typos:
                    return LineResult(et, Confidence.MEDIUM, ClassificationSource.TYPO,
                                      f"{name}+{'+'.join(typos)}", norm)
                return LineResult(et, Confidence.HIGH, ClassificationSource.RULE, name, norm)
    if len(compact) <= SUFFIX_MAX_LEN and not SUFFIX_EXCLUDE.search(norm):
        for (name, rx), et in ((SUFFIX_START, EventType.START), (SUFFIX_END, EventType.END)):
            if rx.search(compact):
                if et == EventType.START and "다시" in compact:
                    name += "+restart"
                return LineResult(et, Confidence.MEDIUM, ClassificationSource.CONTEXT, name, norm)
    if excluded:
        return None
    name, rx = BARE_END
    if rx.match(compact):
        return LineResult(EventType.END, Confidence.MEDIUM, ClassificationSource.CONTEXT, name, norm)
    name, rx = BARE_START
    if rx.match(compact):
        conf = Confidence.MEDIUM if settings.auto_confirm_bare_start else Confidence.LOW
        return LineResult(EventType.START, conf, ClassificationSource.CONTEXT, name, norm)
    name, rx = PRAY_START
    if rx.match(compact):
        conf = Confidence.LOW if typos else Confidence.MEDIUM
        return LineResult(EventType.START, conf, ClassificationSource.CONTEXT, name, norm)
    if len(compact) <= LOOSE_MAX_LEN:
        for (name, rx), et in ((LOOSE_START, EventType.START), (LOOSE_END, EventType.END)):
            if rx.search(compact):
                return LineResult(et, Confidence.LOW, ClassificationSource.CONTEXT, name, norm)
    # 제한적 퍼지 매칭: 짧고 '기도' 관련 글자가 있는 문장만
    if len(compact) <= settings.fuzzy_max_len and re.search(r"[기도마시작끝]", compact):
        dj = _decompose(compact)
        best, best_score = None, 0.0
        for canon, et in CANONICAL.items():
            score = fuzz.ratio(dj, _decompose(canon))
            if score > best_score:
                best, best_score = et, score
        if best is not None and best_score >= settings.fuzzy_threshold:
            return LineResult(best, Confidence.LOW, ClassificationSource.TYPO,
                              f"fuzzy:{best_score:.0f}", norm)
    return None


def classify_message(msg: Message, settings: Settings) -> Event:
    if msg.message_type != MessageType.TEXT:
        return Event(msg.id, EventType.OTHER, Confidence.HIGH, ClassificationSource.RULE,
                     f"non_text:{msg.message_type.value}")
    hits = [r for r in (classify_line(l, settings) for l in msg.raw_text.splitlines()) if r]
    if not hits:
        return Event(msg.id, EventType.OTHER, Confidence.HIGH, ClassificationSource.RULE, "no_match",
                     normalized_text=normalize(msg.raw_text)[0])
    types = {h.event_type for h in hits}
    if len(types) > 1:
        # 한 메시지에 시작과 종료가 함께 있음 → 판단 불가
        return Event(msg.id, EventType.AMBIGUOUS, Confidence.LOW, ClassificationSource.RULE,
                     "start_and_end_in_one", candidate=None,
                     normalized_text=" / ".join(h.normalized for h in hits))
    best = max(hits, key=lambda h: _CONF_ORDER[h.confidence])
    if best.confidence == Confidence.HIGH:
        return Event(msg.id, best.event_type, Confidence.HIGH, best.source, best.rule,
                     normalized_text=best.normalized)
    return Event(msg.id, EventType.AMBIGUOUS, best.confidence, best.source, best.rule,
                 candidate=best.event_type, normalized_text=best.normalized)
