"""사용 설명서 화면 캡처용 데모 대화(가상 인물). 실제 대화 형식(PC 카카오톡 내보내기)을 그대로 따른다.

사용: python docs/manual/demo_chat.py <출력.txt>
"""
from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta

TARGETS = ["김하늘", "이도윤", "박서준", "최유나", "정민재", "강서연", "조은우", "윤지아", "장하람", "임태오"]
OTHERS = ["한목자", "오간사"]
START_DAY, END_DAY = date(2026, 10, 12), date(2026, 10, 25)
SAVED_AT = datetime(2026, 10, 25, 23, 50, 12)

STARTS = ["기도 시작합니다", "기도시작합니다", "기도 시작합니다!", "기도하겠습니다", "기도 시작~", "기도시작합니당"]
ENDS = ["기도 마칩니다", "기도 마쳤습니다", "기도마칩니다", "기도 마쳤습니다!", "기도 마쳤어요", "마칩니다"]
CHATTER = ["오늘 모임 몇 시에 시작해요?", "다들 저녁 맛있게 드세요~", "ㅋㅋㅋㅋ 맞아요", "내일 비 온대요 우산 챙기세요",
           "넵 알겠습니다!", "좋은 아침입니다 ^^", "이번 주 말씀 너무 좋았어요", "사진", "이모티콘", "사진 3장",
           "다음 주 일정 공유드려요", "고생 많으셨습니다", "오늘도 화이팅입니다", "기도 제목 있으면 나눠주세요"]
WEEKDAY = "월화수목금토일"


def fmt(t: datetime) -> str:
    h = t.hour % 12 or 12
    return f"{'오전' if t.hour < 12 else '오후'} {h}:{t.minute:02d}"


def build(seed: int = 7) -> str:
    rnd = random.Random(seed)
    events: list[tuple[datetime, str, str]] = []
    special = {  # 설명서에서 보여줄 사례(검토·오타·이모티콘·재시작 등)
        (date(2026, 10, 24), "조은우"): [(22, 56, "무튼 기도합니다"), (23, 26, "기도 마칩니다")],
        (date(2026, 10, 23), "최유나"): [(21, 10, "기도 시작합니다"), (21, 42, "ㄱ도 마칩니다")],
        (date(2026, 10, 22), "윤지아"): [(20, 30, "기도 시작합니다!"), (21, 2, "기도 마쳤습니다!(별똥별)")],
        (date(2026, 10, 21), "박서준"): [(7, 44, "기도시작합니다"), (9, 4, "기도 다시 시작합니다"), (9, 36, "기도 마칩니다")],
        (date(2026, 10, 25), "장하람"): [(21, 5, "아주 좋아요~~\n기도시작합니다"), (21, 37, "기도 마칩니다")],
        (date(2026, 10, 20), "임태오"): [(22, 30, "기도 시작합니다")],             # 종료 누락 → 미완료
        (date(2026, 10, 25), "이도윤"): [(22, 40, "기도 마칩니다")],                # 시작 누락 → 검토
    }
    skip = {(date(2026, 10, 19), "정민재"), (date(2026, 10, 23), "강서연"), (date(2026, 10, 25), "임태오")}
    d = START_DAY
    while d <= END_DAY:
        for name in TARGETS:
            if (d, name) in special:
                for h, m, text in special[(d, name)]:
                    events.append((datetime(d.year, d.month, d.day, h, m), name, text))
                continue
            if (d, name) in skip or rnd.random() < 0.06:
                continue
            if rnd.random() < 0.18:   # 새벽(다음 날 00:10~03:30) 인증
                start = datetime(d.year, d.month, d.day, 0, 10) + timedelta(days=1, minutes=rnd.randint(0, 200))
            else:
                start = datetime(d.year, d.month, d.day, 20, 0) + timedelta(minutes=rnd.randint(0, 220))
            end = start + timedelta(minutes=rnd.randint(25, 45))
            events.append((start, name, rnd.choice(STARTS)))
            events.append((end, name, rnd.choice(ENDS)))
        for _ in range(rnd.randint(6, 14)):
            t = datetime(d.year, d.month, d.day, 9, 0) + timedelta(minutes=rnd.randint(0, 760))
            events.append((t, rnd.choice(TARGETS + OTHERS), rnd.choice(CHATTER)))
        d += timedelta(days=1)
    events = [e for e in events if e[0] <= SAVED_AT]
    events.sort(key=lambda e: e[0])
    out = ["🌟 하모니 님과 카카오톡 대화", f"저장한 날짜 : {SAVED_AT:%Y-%m-%d %H:%M:%S}", ""]
    cur = None
    for t, name, text in events:
        if t.date() != cur:
            cur = t.date()
            out.append(f"--------------- {cur.year}년 {cur.month}월 {cur.day}일 {WEEKDAY[cur.weekday()]}요일 ---------------")
        out.append(f"[{name}] [{fmt(t)}] {text}")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "demo_chat.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(build())
    print(path)
