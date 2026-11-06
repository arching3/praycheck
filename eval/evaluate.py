"""정답셋(eval/goldset/gold_part*.json) 대비 파서·분류·세션·날짜 귀속 엔진 성능 평가.

사용: .venv\\Scripts\\python eval\\evaluate.py [--per-day-files]
입력: private/날짜별대화/2026년10월{9..30}일.txt (평가 범위 10/10~10/29, 9일·30일은 문맥)
출력: 콘솔 요약 + eval/goldset/report.md (실명 포함 → 커밋 금지)
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from prayer_tracker.config import Settings  # noqa: E402
from prayer_tracker.engine import analyze  # noqa: E402
from prayer_tracker.ingestion.parser import HEADER, parse_text  # noqa: E402
from prayer_tracker.models import Coverage, DayStatus, EventType, MessageType, SessionStatus  # noqa: E402

DAY_DIR = ROOT / "private" / "날짜별대화"
GOLD_DIR = ROOT / "eval" / "goldset"
R0, R1 = date(2026, 10, 10), date(2026, 10, 29)
CTX0, CTX1 = date(2026, 10, 9), date(2026, 10, 30)
GRACE = 4


def day_file(d: date) -> Path:
    return DAY_DIR / f"{d.year}년{d.month}월{d.day}일.txt"


def days(a: date, b: date):
    return [a + timedelta(i) for i in range((b - a).days + 1)]


def in_range(t: datetime) -> bool:
    return R0 <= t.date() <= R1


# ------------------------------------------------------------------ 입력
def load_engine_input(per_day: bool):
    texts = {d: day_file(d).read_text(encoding="utf-8-sig") for d in days(CTX0, CTX1)}
    messages, coverage, issues = [], [], []
    chunks = list(texts.items()) if per_day else [(CTX0, "\n".join(texts.values()))]
    seen = set()
    for _, txt in chunks:
        pr = parse_text(txt)
        issues += pr.issues
        coverage.append(Coverage(datetime.combine(pr.first_date, time(0)), pr.last_message_at))
        for m in pr.messages:
            if m.id not in seen:
                seen.add(m.id)
                messages.append(m)
    return messages, coverage, issues, texts


def load_gold():
    msgs, sessions = [], []
    for p in sorted(GOLD_DIR.glob("gold_part*.json")):
        g = json.loads(p.read_text(encoding="utf-8"))
        msgs += g["messages"]
        sessions += g["sessions"]
    return msgs, sessions


def _dt(o):
    return datetime.strptime(f"{o['date']} {o['time']}", "%Y-%m-%d %H:%M") if o else None


def build_index(messages):
    idx = defaultdict(list)
    for m in messages:
        idx[(m.sender_raw, m.sent_at)].append(m)
    return idx


def resolve(idx, sender, t, text=None, prefer_prayer=False):
    """정답 항목 → 파싱된 메시지. 같은 분에 여러 개면 본문 유사도로 고른다."""
    cands = idx.get((sender, t), [])
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    if text:
        return max(cands, key=lambda m: SequenceMatcher(None, m.raw_text.strip(), text.strip()).ratio())
    if prefer_prayer:
        pr = [m for m in cands if re.search(r"기도|마칩|마쳤|시작|끝", m.raw_text)]
        if pr:
            return pr[0]
    return cands[0]


# ------------------------------------------------------------------ 1. 파서
def eval_parser(texts, messages, issues):
    out = {}
    hdr = cont = date_lines = bracket_non_hdr = blank = 0
    am12 = pm12 = 0
    for d, txt in texts.items():
        if not (R0 <= d <= R1):
            continue
        for line in txt.splitlines():
            if re.match(r"^-+\s*\d{4}년", line.strip()):
                date_lines += 1
            elif HEADER.match(line):
                hdr += 1
                h = HEADER.match(line)
                if h["h"] == "12":
                    am12 += h["ampm"] == "오전"
                    pm12 += h["ampm"] == "오후"
            elif not line.strip():
                blank += 1
            else:
                cont += 1
                if line.startswith("["):
                    bracket_non_hdr += 1
    rng = [m for m in messages if in_range(m.sent_at)]
    out["헤더 줄 수(범위)"] = hdr
    out["파싱된 메시지 수(범위)"] = len(rng)
    out["헤더 수 = 메시지 수"] = hdr == len(rng)
    out["여러 줄 메시지 수"] = sum("\n" in m.raw_text for m in rng)
    out["헤더 아닌 '['로 시작하는 줄(본문에 포함되어야 함)"] = bracket_non_hdr
    out["본문 연속 줄 수"] = cont
    out["오전 12시 → 0시 변환 대상 / 실제 0시 메시지"] = f"{am12} / {sum(m.sent_at.hour == 0 for m in rng)}"
    out["오후 12시 → 12시 변환 대상 / 실제 12시 메시지"] = f"{pm12} / {sum(m.sent_at.hour == 12 for m in rng)}"
    out["메시지 유형"] = dict(Counter(m.message_type.value for m in rng))
    out["파싱 경고"] = Counter(i.reason for i in issues)
    out["파싱 경고 예시"] = [f"{i.text[:60]}" for i in issues[:8]]
    # 연속 줄이 모두 어떤 메시지 본문에 들어갔는가
    body_lines = sum(m.raw_text.count("\n") for m in rng)
    out["본문에 흡수된 연속 줄 수"] = body_lines
    return out


# ------------------------------------------------------------------ 2~4. 판정
def engine_label(ev):
    if ev is None:
        return "OTHER"
    if ev.event_type in (EventType.START, EventType.END):
        return ev.event_type.value
    if ev.event_type == EventType.AMBIGUOUS:
        return f"REVIEW:{ev.candidate.value if ev.candidate else '?'}"
    return "OTHER"


def gold_attribution(gsessions):
    """정답 세션의 귀속 날짜(정책 그대로): 04:00 전 시작 → 전날 완료 기록 없으면 전날, 있으면 당일."""
    by_member = defaultdict(list)
    for s in gsessions:
        if s["start_dt"] and s["end_dt"]:
            by_member[s["sender"]].append(s)
    att = {}
    for sender, ss in by_member.items():
        done = set()
        for s in sorted(ss, key=lambda s: s["start_dt"]):
            d = s["start_dt"].date()
            if s["start_dt"].hour < GRACE:
                prev = d - timedelta(1)
                d = d if prev in done else prev
            att[id(s)] = d
            done.add(d)
    return att


def evaluate(per_day: bool):
    messages, coverage, issues, texts = load_engine_input(per_day)
    gold_msgs, gold_sessions = load_gold()
    idx = build_index(messages)
    report = {"mode": "날짜별 파일 22개 개별 업로드" if per_day else "하나의 내보내기 파일"}
    report["parser"] = eval_parser(texts, messages, issues)

    senders = {g["sender"] for g in gold_msgs if g["label"] in ("START", "END")}
    name_to_id = {n: i for i, n in enumerate(sorted({m.sender_raw for m in messages}), 1)}
    for m in messages:
        m.member_id = name_to_id[m.sender_raw]
    targets = {name_to_id[s] for s in senders if s in name_to_id}
    res = analyze(messages, targets, coverage, settings=Settings())
    id_to_name = {v: k for k, v in name_to_id.items()}

    # --- 메시지 분류
    gold_label, unresolved, uncertain = {}, [], set()
    for g in gold_msgs:
        m = resolve(idx, g["sender"], _dt(g), g.get("text"))
        if m is None:
            unresolved.append(g)
            continue
        if not in_range(m.sent_at):
            continue
        gold_label[m.id] = g["label"]
        if g.get("uncertain"):
            uncertain.add(m.id)
    conf = Counter()
    errors = []
    for m in messages:
        if not in_range(m.sent_at) or m.member_id not in targets or m.message_type != MessageType.TEXT:
            continue
        gl = gold_label.get(m.id, "OTHER")
        el = engine_label(res.events.get(m.id))
        conf[(gl, el)] += 1
        if gl != el.split(":")[0] and not (el.startswith("REVIEW") and m.id in uncertain):
            errors.append((m, gl, el, res.events.get(m.id)))
    report["classification"] = {"confusion": conf, "errors": errors, "unresolved": unresolved,
                                "uncertain": len(uncertain)}

    # --- 세션
    # 세션 끝점은 같은 분에 메시지가 여러 개일 수 있으므로 정답 메시지 목록의 본문으로 고른다
    gold_text = {(g["sender"], g["date"], g["time"], g["label"]): g.get("text") for g in gold_msgs}

    def endpoint(s, which, label):
        o = s[which]
        if not o:
            return None
        text = gold_text.get((s["sender"], o["date"], o["time"], label))
        return resolve(idx, s["sender"], _dt(o), text, prefer_prayer=text is None)

    gs = []
    for s in gold_sessions:
        sm = endpoint(s, "start", "START")
        em = endpoint(s, "end", "END")
        anchor = (sm or em)
        if anchor is None:
            continue
        gs.append({"sender": s["sender"], "start": sm.id if sm else None, "end": em.id if em else None,
                   "start_dt": sm.sent_at if sm else None, "end_dt": em.sent_at if em else None,
                   "note": s.get("note", "")})
    # 중복 제거(경계에 걸친 세션은 두 파트에 모두 있을 수 있음)
    uniq = {}
    for s in gs:
        uniq.setdefault((s["sender"], s["start"], s["end"]), s)
    gs = list(uniq.values())
    att = gold_attribution(gs)

    def touches_range(s_start, s_end):
        return any(t and in_range(t) for t in (s_start, s_end))

    gold_pairs = {(s["start"], s["end"]) for s in gs if s["start"] and s["end"] and touches_range(s["start_dt"], s["end_dt"])}
    eng_pairs = {(s.start_message_id, s.end_message_id) for s in res.sessions
                 if s.status == SessionStatus.COMPLETE and touches_range(s.start_at, s.end_at)}
    tp = gold_pairs & eng_pairs
    report["sessions"] = {
        "gold_complete": len(gold_pairs), "engine_complete": len(eng_pairs), "exact_match": len(tp),
        "precision": len(tp) / len(eng_pairs) if eng_pairs else 0,
        "recall": len(tp) / len(gold_pairs) if gold_pairs else 0,
        "engine_only": eng_pairs - gold_pairs, "gold_only": gold_pairs - eng_pairs,
        "gold_unpaired": [s for s in gs if not (s["start"] and s["end"]) and touches_range(s["start_dt"], s["end_dt"])],
    }

    # --- 날짜 귀속 (정확히 일치한 세션 기준)
    eng_by_pair = {(s.start_message_id, s.end_message_id): s for s in res.sessions}
    att_ok, att_bad = 0, []
    for s in gs:
        p = (s["start"], s["end"])
        if p in tp and id(s) in att:
            e = eng_by_pair[p]
            if e.prayer_date == att[id(s)]:
                att_ok += 1
            else:
                att_bad.append((s, att[id(s)], e.prayer_date, e.date_source))
    report["attribution"] = {"ok": att_ok, "bad": att_bad}

    # --- 일별 상태
    gold_day = {}
    complete_days = defaultdict(set)
    for s in gs:
        if id(s) in att:
            complete_days[s["sender"]].add(att[id(s)])
    partial_days = defaultdict(set)
    for s in gs:
        if not (s["start"] and s["end"]):
            t = s["start_dt"] or s["end_dt"]
            partial_days[s["sender"]].add((t - timedelta(hours=GRACE)).date())
    for sender in senders:
        for d in days(R0, R1):
            if d in complete_days[sender]:
                gold_day[(sender, d)] = "COMPLETE"
            elif d in partial_days[sender]:
                gold_day[(sender, d)] = "INCOMPLETE"
            else:
                gold_day[(sender, d)] = "MISSING"
    dconf = Counter()
    day_errors = []
    for (sender, d), g in gold_day.items():
        e = res.day_status.get((name_to_id[sender], d))
        ev = e.value if e else "NONE"
        dconf[(g, ev)] += 1
        if g != ev:
            day_errors.append((sender, d, g, ev))
    report["days"] = {"confusion": dconf, "errors": day_errors}
    report["reviews"] = Counter(r.review_type.value for r in res.reviews
                                if r.target_date and R0 <= r.target_date <= R1)
    report["_ctx"] = {"res": res, "id_to_name": id_to_name, "msgs": {m.id: m for m in messages}}
    return report


# ------------------------------------------------------------------ 출력
def fmt_conf(conf, rows, cols):
    lines = ["| 정답 \\ 엔진 | " + " | ".join(cols) + " | 합계 |", "|---" * (len(cols) + 2) + "|"]
    for r in rows:
        vals = [conf.get((r, c), 0) for c in cols]
        lines.append(f"| {r} | " + " | ".join(str(v) for v in vals) + f" | {sum(vals)} |")
    return "\n".join(lines)


def render(rep) -> str:
    ctx = rep["_ctx"]
    msgs, names = ctx["msgs"], ctx["id_to_name"]
    L = [f"# 엔진 평가 리포트 — {rep['mode']}", f"평가 범위: {R0} ~ {R1}", ""]
    L.append("## 1. 파서")
    for k, v in rep["parser"].items():
        L.append(f"- {k}: {v}")
    c = rep["classification"]
    conf = c["confusion"]
    L += ["", "## 2. 메시지 분류 (대상자 텍스트 메시지)", f"- 정답 매칭 실패: {len(c['unresolved'])}건, 정답 uncertain: {c['uncertain']}건", ""]
    cols = ["START", "END", "REVIEW:START", "REVIEW:END", "REVIEW:?", "OTHER"]
    L.append(fmt_conf(conf, ["START", "END", "OTHER"], cols))
    auto = {k: v for k, v in conf.items() if k[1] in ("START", "END")}
    auto_ok = sum(v for k, v in auto.items() if k[0] == k[1])
    auto_n = sum(auto.values())
    gold_pos = sum(v for k, v in conf.items() if k[0] in ("START", "END"))
    rev = sum(v for k, v in conf.items() if k[1].startswith("REVIEW"))
    false_auto = sum(v for k, v in auto.items() if k[0] == "OTHER")
    L += ["",
          f"- 자동 확정 정밀도: {auto_ok}/{auto_n} = {auto_ok / auto_n:.1%}" if auto_n else "- 자동 확정 없음",
          f"- 자동 확정 재현율(정답 START/END 중 자동 확정·정확): {auto_ok}/{gold_pos} = {auto_ok / gold_pos:.1%}" if gold_pos else "",
          f"- **일상 대화를 인증으로 자동 확정(치명적 오류): {false_auto}건**",
          f"- 검토로 넘긴 메시지: {rev}건",
          f"- 정답 인증을 OTHER로 놓침: {sum(v for k, v in conf.items() if k[0] in ('START', 'END') and k[1] == 'OTHER')}건", ""]
    L.append("### 분류 불일치 목록")
    for m, gl, el, ev in c["errors"]:
        L.append(f"- `{m.sent_at:%m-%d %H:%M}` {m.sender_raw}: {m.raw_text[:70]!r} — 정답 {gl} / 엔진 {el}"
                 f" ({ev.matched_rule if ev else '-'})")
    if c["unresolved"]:
        L.append("### 정답 매칭 실패")
        for g in c["unresolved"]:
            L.append(f"- {g['date']} {g['time']} {g['sender']} {g.get('text', '')[:40]!r} {g['label']}")
    s = rep["sessions"]
    L += ["", "## 3. 세션 매칭 (완료 세션, 시작·종료 쌍 정확 일치)",
          f"- 정답 {s['gold_complete']} / 엔진 {s['engine_complete']} / 일치 {s['exact_match']}",
          f"- 정밀도 {s['precision']:.1%}, 재현율 {s['recall']:.1%}", "", "### 엔진에만 있는 세션"]

    def pair_str(p):
        a, b = (msgs.get(p[0]), msgs.get(p[1]))
        return (f"{a.sender_raw if a else '?'} {a.sent_at:%m-%d %H:%M} {a.raw_text[:20]!r} → "
                f"{b.sent_at:%m-%d %H:%M} {b.raw_text[:20]!r}") if a and b else str(p)
    for p in sorted(s["engine_only"], key=lambda p: msgs[p[0]].sent_at):
        L.append(f"- {pair_str(p)}")
    L.append("### 정답에만 있는 세션")
    for p in sorted(s["gold_only"], key=lambda p: msgs[p[0]].sent_at):
        L.append(f"- {pair_str(p)}")
    L.append("### 정답상 짝이 없는 시작/종료")
    for g in s["gold_unpaired"]:
        t = g["start_dt"] or g["end_dt"]
        L.append(f"- {g['sender']} {t:%m-%d %H:%M} {'시작만' if g['start'] else '종료만'} {g['note'][:60]}")
    a = rep["attribution"]
    n = a["ok"] + len(a["bad"])
    L += ["", "## 4. 날짜 귀속 (일치한 세션 기준)", f"- 정확: {a['ok']}/{n}" + (f" = {a['ok'] / n:.1%}" if n else "")]
    for g, gd, ed, src in a["bad"]:
        L.append(f"- {g['sender']} {g['start_dt']:%m-%d %H:%M} 정답 {gd} / 엔진 {ed} ({src.value if src else '-'})")
    d = rep["days"]
    L += ["", "## 5. 일별 인증 상태 (참여자 × 날짜)", ""]
    L.append(fmt_conf(d["confusion"], ["COMPLETE", "INCOMPLETE", "MISSING"],
                      ["COMPLETE", "INCOMPLETE", "MISSING", "PENDING_REVIEW", "PENDING_DATA", "NONE"]))
    tot = sum(d["confusion"].values())
    agree = sum(v for k, v in d["confusion"].items() if k[0] == k[1])
    false_complete = sum(v for k, v in d["confusion"].items() if k[1] == "COMPLETE" and k[0] != "COMPLETE")
    L += ["", f"- 일치: {agree}/{tot} = {agree / tot:.1%}",
          f"- **잘못된 완료 판정(치명적): {false_complete}건**",
          f"- 검토/데이터 대기로 보류: {sum(v for k, v in d['confusion'].items() if k[1].startswith('PENDING'))}건", "",
          "### 불일치 목록"]
    for sender, day, g, e in sorted(d["errors"], key=lambda x: (x[1], x[0])):
        L.append(f"- {day} {sender}: 정답 {g} / 엔진 {e}")
    L += ["", "## 6. 생성된 검토 항목 (범위 내)", f"- {dict(rep['reviews'])}"]
    return "\n".join(L)


if __name__ == "__main__":
    per_day = "--per-day-files" in sys.argv
    rep = evaluate(per_day)
    text = render(rep)
    out = GOLD_DIR / ("report_per_day.md" if per_day else "report.md")
    out.write_text(text, encoding="utf-8")
    print(text)
