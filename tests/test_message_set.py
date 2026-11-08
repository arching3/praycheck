"""메시지 단위 확장 테스트셋 검사.

데이터
  tests/fixtures/message_set.jsonl      : 변형·함정 문장(src=aug, 생성). 저장소에 포함.
  eval/goldset/message_set_real.jsonl   : 실제 대화에서 뽑아 익명화한 문장(src=real). 공개하지 않음(git 제외) —
                                          있으면 함께 검사하고, 없으면(CI 등) 생성 문장만 검사한다.
label = 신중한 관리자가 그 메시지 하나만 보고 내릴 판단
  START/END: 본인의 기도 시작/종료 인증, OTHER: 그 외, BOTH: 한 메시지에 시작·종료, UNSURE: 문맥 없이는 판단 불가.

지켜야 할 것(실패하면 안 됨):
  1. OTHER를 시작/종료로 자동 확정(HIGH)하지 않는다. 문맥 자동 확정 후보(MEDIUM)로도 올리지 않는다.
  2. START를 종료로, END를 시작으로 (확정이든 후보든) 보지 않는다.
  3. BOTH·UNSURE는 자동 확정하지 않는다(검토 또는 무시).
  4. START/END를 OTHER로 놓치지 않는다. 단, 지금 엔진의 알려진 한계는 행의 known_miss에 사유를 적어 둔다.
     (규칙을 고쳐 잡게 되면 known_miss를 지운다 — 남겨 두면 '이제 잡힘'으로 실패해 알려 준다.)
실행 요약: python tests/test_message_set.py  (유형별 표)
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prayer_tracker.classification.classifier import classify_message  # noqa: E402
from prayer_tracker.config import Settings  # noqa: E402
from prayer_tracker.models import Confidence, EventType, Message, MessageType  # noqa: E402

DATA = Path(__file__).parent / "fixtures" / "message_set.jsonl"
REAL = Path(__file__).resolve().parents[1] / "eval" / "goldset" / "message_set_real.jsonl"
ROWS = [json.loads(l) for f in (DATA, REAL) if f.exists()
        for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
if not ROWS:
    pytest.skip("메시지 테스트셋 없음", allow_module_level=True)
S = Settings()

def engine(text: str) -> str:
    """AUTO_START / AUTO_END / MED_START / MED_END / LOW_START / LOW_END / LOW_? / OTHER"""
    ev = classify_message(Message("t", "참여자A", datetime(2026, 11, 1, 22), text, MessageType.TEXT), S)
    if ev.event_type in (EventType.START, EventType.END):
        return "AUTO_" + ev.event_type.value
    if ev.event_type == EventType.AMBIGUOUS:
        lvl = "MED" if ev.confidence == Confidence.MEDIUM else "LOW"
        return f"{lvl}_{ev.candidate.value if ev.candidate else '?'}"
    return "OTHER"


def violation(row: dict, out: str) -> str | None:
    lab = row["label"]
    if lab == "OTHER" and (out.startswith("AUTO_") or out.startswith("MED_")):
        return "일상 대화를 인증(후보)으로 봄"
    if lab == "START" and out.endswith("_END"):
        return "시작을 종료로 봄"
    if lab == "END" and out.endswith("_START"):
        return "종료를 시작으로 봄"
    if lab in ("BOTH", "UNSURE") and out.startswith("AUTO_"):
        return "판단 불가 메시지를 자동 확정"
    if lab in ("START", "END") and out == "OTHER" and not row.get("known_miss"):
        return "인증을 놓침"
    if row.get("known_miss") and out != "OTHER":
        return "알려진 한계였는데 이제 잡힘 — known_miss를 지우세요"
    return None


def test_dataset_shape():
    assert 0 < len(ROWS) <= 1000
    assert len({r["id"] for r in ROWS}) == len(ROWS)
    assert len({r["text"].strip() for r in ROWS}) == len(ROWS)
    assert {r["label"] for r in ROWS} <= {"START", "END", "OTHER", "BOTH", "UNSURE"}
    assert all(r["label"] in ("START", "END") for r in ROWS if r.get("known_miss"))


@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_message(row):
    out = engine(row["text"])
    v = violation(row, out)
    assert v is None, f"{v}: {row['text']!r} (정답 {row['label']}, 엔진 {out})"


def report() -> None:
    by = defaultdict(Counter)
    bad = []
    for r in ROWS:
        out = engine(r["text"])
        by[r["label"]][out] += 1
        if (v := violation(r, out)):
            bad.append((r["id"], v, r["label"], out, r["text"]))
    cols = ["AUTO_START", "AUTO_END", "MED_START", "MED_END", "LOW_START", "LOW_END", "LOW_?", "OTHER"]
    print(f"총 {len(ROWS)}개  {dict(Counter(r['src'] for r in ROWS))}")
    print("정답\\엔진  " + "  ".join(cols))
    for lab in ("START", "END", "OTHER", "BOTH", "UNSURE"):
        print(f"{lab:8} " + "  ".join(f"{by[lab][c]:>{len(c)}}" for c in cols))
    auto = [(r, engine(r["text"])) for r in ROWS]
    ok = sum(1 for r, o in auto if o == f"AUTO_{r['label']}")
    n_auto = sum(1 for _, o in auto if o.startswith("AUTO_"))
    gaps = Counter(r["known_miss"] for r in ROWS if r.get("known_miss"))
    print(f"자동 확정 정밀도 {ok}/{n_auto}, 위반 {len(bad)}건, 알려진 한계 {sum(gaps.values())}건")
    for k, v in gaps.most_common():
        print(f"   {v:3} {k}")
    for b in bad:
        print("  ", *b[:4], repr(b[4]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    report()
