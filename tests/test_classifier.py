import pytest

from conftest import msg
from prayer_tracker.classification.classifier import classify_message, normalize
from prayer_tracker.config import Settings
from prayer_tracker.models import Confidence, EventType, MessageType

S = Settings()


def cls(text, settings=S, **kw):
    return classify_message(msg(text, 26, 22, **kw), settings)


@pytest.mark.parametrize("text", ["기도 시작합니다", "기도시작합니다", "기도 시작합니다~", "기도를 시작하겠습니다!!"])
def test_explicit_start_high(text):
    ev = cls(text)
    assert (ev.event_type, ev.confidence) == (EventType.START, Confidence.HIGH)


@pytest.mark.parametrize("text", ["기도 마칩니다", "기도 마쳤습니다.", "기도마칩니다 ㅎㅎ", "기도 끝났습니다"])
def test_explicit_end_high(text):
    ev = cls(text)
    assert (ev.event_type, ev.confidence) == (EventType.END, Confidence.HIGH)


def test_tc02_typo_giyeok_is_candidate_not_high():
    ev = cls("ㄱ도 마칩니다")
    assert ev.event_type == EventType.AMBIGUOUS
    assert ev.candidate == EventType.END
    assert ev.confidence == Confidence.MEDIUM


def test_tc03_colloquial_start_and_end():
    s = cls("기도시작합니당")
    assert s.event_type == EventType.AMBIGUOUS and s.candidate == EventType.START
    assert s.confidence == Confidence.MEDIUM
    e = cls("마쳤습니다아")
    assert e.event_type == EventType.AMBIGUOUS and e.candidate == EventType.END


def test_bare_end_is_medium_candidate():
    ev = cls("마칩니다")
    assert ev.event_type == EventType.AMBIGUOUS and ev.candidate == EventType.END
    assert ev.matched_rule == "bare_end"


def test_bare_start_is_low_by_default_medium_when_enabled():
    assert cls("시작합니다").confidence == Confidence.LOW
    ev = cls("시작합니다", Settings(auto_confirm_bare_start=True))
    assert ev.confidence == Confidence.MEDIUM


def test_tc04_loose_start_is_low_candidate():
    ev = cls("무튼 기도합니다")
    assert ev.event_type == EventType.AMBIGUOUS
    assert ev.candidate == EventType.START
    assert ev.confidence == Confidence.LOW


def test_tc05_prayer_response_not_confirmed():
    ev = cls("기도했습니다! 조금 뒤에 더 길게 기도할 때에도 기도하겠습니다~!")
    assert ev.event_type in (EventType.OTHER, EventType.AMBIGUOUS)
    assert ev.confidence != Confidence.HIGH or ev.event_type == EventType.OTHER


def test_tc06_multiline_start_detected():
    ev = cls("아주 좋아요~~\n기도시작합니다")
    assert ev.event_type == EventType.START


@pytest.mark.parametrize("text", [
    "오늘 기도회 누구니?",
    "기도해주셔서 감사합니다",
    "기도 시작-마침 안 올리는 사람 체크해줘",
    "내일을 위해 기도 부탁드립니다",
])
def test_tc13_false_positives_not_confirmed(text):
    ev = cls(text)
    assert ev.event_type not in (EventType.START, EventType.END)


def test_start_and_end_in_one_message_is_ambiguous():
    ev = cls("기도 시작합니다\n기도 마칩니다")
    assert ev.event_type == EventType.AMBIGUOUS and ev.candidate is None


@pytest.mark.parametrize("mt", [MessageType.MEDIA, MessageType.DELETED, MessageType.SYSTEM])
def test_non_text_is_other(mt):
    ev = classify_message(msg("기도 시작합니다", 26, 22, mtype=mt), S)
    assert ev.event_type == EventType.OTHER


def test_normalize_strips_trailing_noise_without_typo():
    s, typos = normalize("기도 시작합니다~~ ㅎㅎ")
    assert s == "기도 시작합니다" and typos == []


def test_ordinary_chat_is_other():
    assert cls("오늘 날씨가 좋네요").event_type == EventType.OTHER


# --- 평가(10/10~10/29 정답셋)에서 발견된 사례 -----------------------------------
def classify(text):
    return classify_message(msg(text, 26, 22), Settings())


@pytest.mark.parametrize("text,et", [
    ("기도 마쳤습니다!(별똥별)", EventType.END),
    ("기도 마쳤습니다!(강아지)", EventType.END),
    ("(하트)기도 시작합니다", EventType.START),
])
def test_kakao_emoticon_text_is_stripped(text, et):
    e = classify(text)
    assert e.event_type == et and e.confidence == Confidence.HIGH


@pytest.mark.parametrize("text,cand", [
    ("감사한 마음을 가지고 기도 시작합니다!", EventType.START),
    ("주님께 내일을 맡겨드리며 기도 시작합니다", EventType.START),
    ("아까 기도 마쳤습니다", EventType.END),
])
def test_explicit_phrase_at_sentence_end_is_medium_candidate(text, cand):
    e = classify(text)
    assert e.event_type == EventType.AMBIGUOUS and e.candidate == cand
    assert e.confidence == Confidence.MEDIUM and e.matched_rule.endswith("suffix")


@pytest.mark.parametrize("text", [
    "기도했습니다! 조금 뒤에 더 길게 기도할 때에도 기도하겠습니다~!",
    "기도 곧 시작하는데 다들 어디갔어?",
    "(슬픔)모티브 구절(슬픔)",
    "원투원 마쳤습니다^__^",
])
def test_suffix_and_emoticon_rules_do_not_add_false_positives(text):
    assert classify(text).event_type == EventType.OTHER


@pytest.mark.parametrize("text", ["다시 기도 시작합니다!", "기도 다시 시작합니다", "아까 기도하다가 잠들어서...\n다시 기도 시작합니다!"])
def test_restart_rule(text):
    e = classify(text)
    assert e.event_type == EventType.START and e.matched_rule == "start_restart"


# --- 해요체 어미("기도 마쳤어요", 2026-10-30 실데이터에서 발견) ----------------------
@pytest.mark.parametrize("text,et", [
    ("기도 마쳤어요", EventType.END),
    ("기도마쳤어요", EventType.END),
    ("기도 끝냈어요", EventType.END),
    ("기도 완료했어요", EventType.END),
    ("기도 시작해요", EventType.START),
    ("기도 시작 할게요!!", EventType.START),
])
def test_polite_yo_endings_are_high(text, et):
    e = classify(text)
    assert e.event_type == et and e.confidence == Confidence.HIGH


@pytest.mark.parametrize("text,cand,rule", [
    ("기도 마쳤어용", EventType.END, "colloquial_yong"),
    ("기도 끝했어요", EventType.END, "typo_kkeut"),
    ("마쳤어요", EventType.END, "bare_end"),
    ("오늘도 감사하며 기도 마쳤어요", EventType.END, "end_suffix"),
])
def test_yo_variants_are_medium_candidates(text, cand, rule):
    e = classify(text)
    assert e.event_type == EventType.AMBIGUOUS and e.candidate == cand and e.confidence == Confidence.MEDIUM
    assert rule in e.matched_rule


@pytest.mark.parametrize("text", ["끝났어요", "회의 마쳤어요?", "기도 끝났어요?", "다들 끝나고 뭐해요", "봉사 끝나고 올게요.."])
def test_yo_rules_do_not_add_false_positives(text):
    assert classify(text).event_type == EventType.OTHER
