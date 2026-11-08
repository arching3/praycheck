"""Streamlit 관리자 UI. 실행: streamlit run prayer_tracker/ui/app.py"""
from __future__ import annotations

import html
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from prayer_tracker import __version__, updater  # noqa: E402
from prayer_tracker.models import DayStatus, EventType, ReviewType  # noqa: E402
from prayer_tracker.reports import export, pdf, summary  # noqa: E402
from prayer_tracker.service import DEFAULT_DB, PrayerService  # noqa: E402
from prayer_tracker.ui.dashboard_widgets import (  # noqa: E402
    WEEKDAYS, month_picker, person_calendar, timeline,
)

st.set_page_config(page_title="기도 인증 현황", layout="wide")

STATUS_COLORS = {"완료": "#c8e6c9", "미완료": "#ffe0b2", "미인증": "#ffcdd2",
                 "검토 대기": "#fff59d", "데이터 확인 대기": "#e0e0e0"}
REVIEW_PAGE_SIZE = 10
REVIEW_TYPE_KO = {
    ReviewType.MISSING_START: "시작 누락", ReviewType.MISSING_END: "종료 누락",
    ReviewType.DUPLICATE_START: "시작 중복", ReviewType.DUPLICATE_END: "종료 중복",
    ReviewType.AMBIGUOUS: "의미 불확실", ReviewType.DATE_ASSIGNMENT: "날짜 귀속",
    ReviewType.DUPLICATE_MESSAGE: "중복 메시지",
}


# ------------------------------------------------------------------ 공통
def get_service() -> PrayerService:
    if "service" not in st.session_state:
        st.session_state["service"] = PrayerService(st.session_state.get("db_path", DEFAULT_DB))
    return st.session_state["service"]


def color_status(df: pd.DataFrame):
    fn = getattr(df.style, "map", None) or df.style.applymap
    return fn(lambda v: f"background-color: {STATUS_COLORS[v]}; color: #000" if v in STATUS_COLORS else "")


def show_table(rows: list[dict], styled: bool = False):
    if not rows:
        st.info("표시할 데이터가 없습니다.")
        return
    df = pd.DataFrame(rows)
    st.dataframe(color_status(df) if styled else df, hide_index=True, width="stretch")


def all_dates(svc) -> list[date]:
    return sorted({d for (_, d) in svc.result.day_status})


def open_reviews(svc, include_held: bool = False):
    ok = ("OPEN", "HELD") if include_held else ("OPEN",)
    return [r for r in svc.result.reviews if r.status in ok]


def msg_line(m) -> str:
    return f"`{m.sent_at:%m-%d %H:%M}` **{m.sender_raw}**: {m.raw_text}"


# ------------------------------------------------------------------ 판정 피드백
FEEDBACK_CSS = """<style>
.pc-msg{padding:4px 10px;border-left:4px solid transparent;border-radius:4px;line-height:1.5}
.pc-admin{border-left-color:#2e9d5b;color:#2e9d5b}
.pc-other{border-left-color:#9a9a9a;color:#9a9a9a}
.pc-other .pc-text{text-decoration:line-through}
.pc-auto{border-left-color:rgba(46,157,91,.35)}
.pc-cand{border-left-color:#e08a1e}
.pc-badge{font-size:.78em;font-weight:600;padding:1px 7px;border-radius:9px;border:1px solid currentColor;
          margin-left:6px;white-space:nowrap}
.pc-cand .pc-badge{color:#e08a1e}
.pc-flash{animation:pcflash 1.8s ease-out}
@keyframes pcflash{0%{background:rgba(46,157,91,.40)}100%{background:transparent}}
.pc-done{border:1px solid #2e9d5b;border-left:6px solid #2e9d5b;border-radius:6px;padding:8px 12px;
         margin:4px 0 8px}
.pc-done-title{color:#2e9d5b;font-weight:700}
/* 사이드바 메뉴 버튼: 큰 글자, 넉넉한 높이, 왼쪽 정렬 */
.st-key-pc_nav{gap:.4rem}
.st-key-pc_nav button{min-height:3rem;justify-content:flex-start;padding:.4rem 1rem}
.st-key-pc_nav button > div{justify-content:flex-start}
.st-key-pc_nav button p{font-size:1.15rem;font-weight:500;text-align:left}
.st-key-pc_nav button[kind="primary"] p{font-weight:700}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{font-size:.95rem}
</style>"""
ET_KO = {EventType.START: "시작(START)", EventType.END: "종료(END)", EventType.OTHER: "인증 아님(OTHER)"}


def open_review_keys(svc) -> set[str]:
    return {r.key for r in svc.result.reviews if r.status in ("OPEN", "HELD")}


def act(svc, desc: str, do, undo=None, gkey: str | None = None, snapshot: dict | None = None,
        touched: tuple[str, ...] = ()) -> None:
    """관리자 판정 실행 + 시각적 피드백(알림, 방금 바뀐 줄 강조, 해결된 항목 카드, 되돌리기)."""
    ss = st.session_state
    before = open_review_keys(svc)
    do()
    solved = len(before - open_review_keys(svc))
    ss["toast"] = f"{desc}" + (f" · 검토 {solved}건 해결" if solved else "")
    ss["just_touched"] = set(touched)
    if gkey:
        ss.setdefault("recent", {})[gkey] = snapshot
        if undo:
            ss.setdefault("undo", {})[gkey] = (undo, desc)
    st.rerun()


def _msg_html(m, cls: str, badge: str) -> str:
    text = html.escape(m.raw_text).replace("\n", "<br>")
    flash = " pc-flash" if m.id in st.session_state.get("just_touched", ()) else ""
    return (f"<div class='pc-msg {cls}{flash}'><code>{m.sent_at:%m-%d %H:%M}</code> "
            f"<b>{html.escape(m.sender_raw)}</b>: <span class='pc-text'>{text}</span>{badge}</div>")


def message_html(svc, m, labels: dict) -> str:
    """판정 상태에 따라 색을 입힌 메시지 한 줄."""
    lab = labels.get(m.id)
    if lab in (EventType.START, EventType.END):
        return _msg_html(m, "pc-admin", f"<span class='pc-badge'>✅ {lab.value} 지정됨</span>")
    if lab == EventType.OTHER:
        return _msg_html(m, "pc-other", "<span class='pc-badge'>⛔ OTHER 지정됨</span>")
    e = svc.result.events.get(m.id)
    if e and e.event_type in (EventType.START, EventType.END):
        return _msg_html(m, "pc-auto", f"<span class='pc-badge'>자동 {e.event_type.value}</span>")
    if e and e.event_type == EventType.AMBIGUOUS:
        cand = e.candidate.value if e.candidate else "?"
        return _msg_html(m, "pc-cand", f"<span class='pc-badge'>{cand} 후보?</span>")
    return _msg_html(m, "", "")


def message_row(svc, m, prefix: str, link_group: str | None = None, gkey: str | None = None,
                snapshot: dict | None = None, labels: dict | None = None):
    """메시지 한 줄 + 판정 버튼. 지정된 버튼은 '✓'로 채워지고, 다시 누르면 지정이 해제된다."""
    labels = svc.decisions().labels if labels is None else labels
    cur = labels.get(m.id)
    cols = st.columns([5, 1, 1, 1, 1] if link_group else [6, 1, 1, 1])
    cols[0].markdown(message_html(svc, m, labels), unsafe_allow_html=True)
    for col, et in zip(cols[1:4], (EventType.START, EventType.END, EventType.OTHER)):
        on = cur == et
        if col.button(f"✓ {et.value}" if on else et.value, key=f"{prefix}|{et.value}|{m.id}",
                      type="primary" if on else "secondary", width="stretch",
                      help="다시 누르면 지정을 해제합니다" if on else f"{ET_KO[et]}로 지정"):
            new = None if on else et
            desc = (f"↩ {m.sent_at:%m-%d %H:%M} 지정 해제" if on
                    else f"✅ {m.sent_at:%m-%d %H:%M} 메시지를 {ET_KO[et]}로 지정")
            act(svc, desc, lambda: svc.label_message(m.id, new), lambda: svc.label_message(m.id, cur),
                gkey, snapshot, (m.id,))
    if link_group:
        cols[4].checkbox("연결 선택", key=f"sel|{link_group}|{prefix}|{m.id}")


def selected_ids(group_key: str) -> list[str]:
    out = []
    for k, v in st.session_state.items():
        if v and isinstance(k, str) and k.startswith(f"sel|{group_key}|"):
            out.append(k.rsplit("|", 1)[1])
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------ 페이지
def page_dashboard(svc):
    dates = all_dates(svc)
    if not dates:
        st.info("현황이 없습니다. '업로드'에서 대화 파일을 올리고 '참여자 설정'에서 대상자를 선택해 주세요.")
        return
    n_open = len(open_reviews(svc))
    if n_open:
        st.warning(f"검토가 필요한 항목이 {n_open}건 있습니다. 사이드바의 '검토' 페이지에서 처리해 주세요.")
    d = month_picker(svc, dates)
    st.divider()
    s = summary.day_summary(svc, d)
    cols = st.columns(6)
    for c, label in zip(cols, ["완료", "미완료", "미인증", "검토 대기", "데이터 확인 대기"]):
        c.metric(label, s[label])
    last = s["마지막 반영 시각"]
    cols[5].metric("마지막 반영", last[5:16] if last else "-", help=last or None)
    st.subheader(f"{d} ({WEEKDAYS[(d.weekday() + 1) % 7]}) 타임라인")
    timeline(svc, d)
    st.subheader(f"{d} 현황")
    rows = summary.day_overview(svc, d)
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(color_status(df.rename(columns={"인증 상태": "인증 상태"})), hide_index=True,
                     width="stretch")
    else:
        st.info("대상 참여자가 없습니다.")
    person_buttons(svc, "dash")
    with st.expander("참여자별 세션 보기"):
        det = summary.session_details(svc, d, d)
        if not det:
            st.caption("이 날짜에 귀속된 세션이 없습니다.")
        for r in det:
            st.markdown(f"- **{r['참여자 이름']}** · {r['세션 상태']} · {r['시작 시각']} → {r['종료 시각'] or '?'} "
                        f"· {r['기도 시간'] or '-'} · {r['날짜 귀속 여부']}")
    st.subheader("참여자 × 날짜 현황")
    show_table(summary.daily_matrix(svc), styled=True)


def go(page: str, **state) -> None:
    """다른 페이지로 이동(사이드바 메뉴 버튼의 강조도 따라 바뀐다)."""
    st.session_state.update(state)
    st.session_state["page"] = page
    st.rerun()


def person_buttons(svc, where: str, selected: int | None = None) -> None:
    """대상자 이름 버튼 줄. 누르면 개인별 현황으로 이동."""
    names = svc.member_names()
    targets = sorted(svc.targets(), key=lambda i: names.get(i, ""))
    if not targets:
        return
    if where != "person":
        st.caption("이름을 누르면 개인별 현황을 봅니다.")
    per_row = 6
    for i in range(0, len(targets), per_row):
        cols = st.columns(per_row)
        for c, mid in zip(cols, targets[i:i + per_row]):
            if c.button(names.get(mid, str(mid)), key=f"pb|{where}|{mid}", width="stretch",
                        type="primary" if mid == selected else "secondary"):
                go("person", person_id=mid)


def page_person(svc):
    names = svc.member_names()
    targets = sorted(svc.targets(), key=lambda i: names.get(i, ""))
    if not targets:
        st.info("대상 참여자가 없습니다. '참여자 설정'에서 대상자를 선택해 주세요.")
        return
    mid = st.session_state.get("person_id")
    if mid not in targets:
        mid = targets[0]
        st.session_state["person_id"] = mid
    person_buttons(svc, "person", selected=mid)
    st.subheader(names.get(mid, str(mid)))

    p = summary.person_summary(svc, mid)
    # 값이 잘리지 않도록 3칸씩 두 줄
    rate = f"{p['완료율']:.0%}" if p["완료율"] is not None else "-"
    r1, r2 = st.columns(3), st.columns(3)
    r1[0].metric("완료율", rate, help=f"완료 {p['완료일']}일 / 확정된 날 {p['확정된 날']}일 "
                                       "(검토 대기·데이터 확인 대기인 날 제외)")
    r1[1].metric("미인증", f"{p['미인증 일수']}일")
    r1[2].metric("미완료", f"{p['미완료 일수']}일")
    r2[0].metric("평균 기도 시간", p["평균 기도 시간"] or "-")
    r2[1].metric("총 기도 시간", p["총 기도 시간"] or "-")
    r2[2].metric("검토 대기", f"{p['검토 대기']}건")

    dates = all_dates(svc)
    if not dates:
        return
    d = person_calendar(svc, mid, dates)
    st.markdown(f"**{d} 세션**")
    det = summary.session_details(svc, d, d, member_id=mid)
    if det:
        show_table([{k: r[k] for k in ("세션 상태", "시작 시각", "종료 시각", "기도 시간", "날짜 귀속 여부")}
                    for r in det])
    else:
        st.caption("이 날짜에 귀속된 세션이 없습니다.")
    if st.button(f"＋ {d} 수동 기록 추가", key="person_add_manual"):
        st.session_state.pop("manual_edit", None)
        go("manual", mf_prefill={"mf_member": mid, "mf_date": d, "mf_note": ""})

    tabs = st.tabs(["세션 목록", "미인증·미완료 날짜", f"검토 항목 ({p['검토 대기']})"])
    with tabs[0]:
        rows = summary.session_details(svc, member_id=mid)
        show_table([{k: r[k] for k in ("날짜", "인증 상태", "세션 상태", "시작 시각", "종료 시각", "기도 시간",
                                       "날짜 귀속 여부", "입력 방식", "검토 여부")} for r in reversed(rows)])
        if rows:
            st.download_button("이 참여자의 세션 CSV 받기", export.to_csv_bytes(rows),
                               file_name=f"세션_{names.get(mid, mid)}.csv", mime="text/csv")
    with tabs[1]:
        show_table(summary.person_days(svc, mid, (DayStatus.MISSING, DayStatus.INCOMPLETE)))
    with tabs[2]:
        groups: dict = {}
        for r in open_reviews(svc, include_held=True):
            if r.member_id == mid:
                groups.setdefault(f"p{mid}~{r.target_date}", []).append(r)
        review_list(svc, groups, prefix=f"p{mid}~")


def review_snapshot(group: list, gkey: str) -> dict:
    r0 = group[0]
    return {"gkey": gkey, "member_id": r0.member_id, "target_date": r0.target_date,
            "message_ids": list(dict.fromkeys(i for r in group for i in r.message_ids)),
            "types": ", ".join(REVIEW_TYPE_KO.get(r.review_type, r.review_type.value) for r in group),
            "review_keys": [r.key for r in group]}


def render_review(svc, key: str, group: list):
    r0 = group[0]
    names = svc.member_names()
    msgs = svc.messages_by_id()
    labels = svc.decisions().labels
    snap = review_snapshot(group, key)
    member = names.get(r0.member_id, "?")
    held = all(r.status == "HELD" for r in group)
    touched = key in st.session_state.get("recent", {})
    with st.expander(f"{'🟢 ' if touched else ''}{member} · {r0.target_date or '날짜 미정'} · {snap['types']}"
                     f"{' (보류)' if held else ''}", expanded=not held or touched):
        hc = st.columns([5, 1])
        hc[0].markdown(f"**참여자**: {member}  \n**대상 날짜**: {r0.target_date or '-'}")
        if st.session_state.get("page") != "person" and \
                hc[1].button("개인별 현황", key=f"toperson|{key}", width="stretch"):
            go("person", person_id=r0.member_id)
        if touched:
            undo_button(svc, key)
        for r in group:
            st.markdown(f"**사유**: {r.reason}")
            ids = [i for i in r.message_ids if i in msgs]
            st.markdown("**후보 메시지**")
            for mid in ids:
                message_row(svc, msgs[mid], f"c|{r.key}", link_group=key, gkey=key, snapshot=snap, labels=labels)
            c = st.columns(4)
            if c[0].button("선택한 두 메시지 연결", key=f"link|{r.key}"):
                chosen = [i for i in selected_ids(key) if i in msgs]
                if len(chosen) != 2:
                    st.error("메시지를 정확히 2개 선택해 주세요.")
                else:
                    a, b = sorted(chosen, key=lambda i: msgs[i].sort_key)
                    act(svc, f"🔗 {msgs[a].sent_at:%H:%M} → {msgs[b].sent_at:%H:%M} 세션으로 연결",
                        lambda: svc.link_messages(a, b), lambda: svc.unlink(a), key, snap, (a, b))
            if c[1].button("올바른 후보 없음", key=f"nocand|{r.key}"):
                act(svc, "✅ '올바른 후보 없음'으로 처리", lambda: svc.set_review_status(r.key, "NO_CANDIDATE"),
                    lambda: svc.set_review_status(r.key, None), key, snap)
            if c[2].button("보류", key=f"hold|{r.key}"):
                act(svc, "⏸ 보류함", lambda: svc.set_review_status(r.key, "HELD"),
                    lambda: svc.set_review_status(r.key, None), key, snap)
            if r.status == "HELD" and c[3].button("다시 열기", key=f"reopen|{r.key}"):
                act(svc, "↩ 다시 열었음", lambda: svc.set_review_status(r.key, None))
            if r.review_type == ReviewType.DATE_ASSIGNMENT and ids:
                dc = st.columns([2, 2, 4])
                nd = dc[0].date_input("귀속 날짜", value=r.target_date or date.today(), key=f"dt|{r.key}")
                if dc[1].button("이 날짜로 귀속", key=f"setdate|{r.key}"):
                    prev = svc.decisions().date_overrides.get(ids[0])
                    act(svc, f"📅 {nd}로 귀속", lambda: svc.set_session_date(ids[0], nd),
                        lambda: svc.set_session_date(ids[0], prev), key, snap, (ids[0],))
        known = [i for i in snap["message_ids"] if i in msgs]
        if known:
            center = msgs[known[0]].sent_at
            # 접힌 expander도 내용을 매번 그리므로, 켤 때만 그리는 toggle을 쓴다(성능).
            tc = st.columns(2)
            if tc[0].toggle("앞뒤 대화 보기 (이 참여자)", key=f"ctxm|{key}"):
                for m in svc.context_messages(center, r0.member_id):
                    message_row(svc, m, f"m|{key}", link_group=key, gkey=key, snapshot=snap, labels=labels)
            if tc[1].toggle("앞뒤 대화 보기 (전체 채팅)", key=f"ctxa|{key}"):
                for m in svc.context_messages(center, None):
                    message_row(svc, m, f"a|{key}", link_group=key, gkey=key, snapshot=snap, labels=labels)


def undo_button(svc, gkey: str) -> None:
    undo = st.session_state.get("undo", {}).get(gkey)
    if undo and st.button(f"↩ 되돌리기: {undo[1]}", key=f"undo|{gkey}"):
        fn, _ = undo
        st.session_state["undo"].pop(gkey, None)
        st.session_state["recent"].pop(gkey, None)
        fn()
        st.session_state["toast"] = "↩ 되돌렸습니다"
        st.rerun()


def render_resolved(svc, snap: dict) -> None:
    """방금 해결된 검토 항목: 사라지지 않고 같은 자리에 '처리 완료' 카드로 남는다."""
    names = svc.member_names()
    msgs = svc.messages_by_id()
    labels = svc.decisions().labels
    ids = set(snap["message_ids"])
    sess = [s for s in svc.result.sessions if s.member_id == snap["member_id"]
            and ({s.start_message_id, s.end_message_id} & ids)]
    lines = []
    for s in sess:
        if s.duration_seconds is not None:
            lines.append(f"✅ 세션 {s.start_at:%m-%d %H:%M} → {s.end_at:%H:%M} "
                         f"({s.duration_seconds // 60}분) · {s.prayer_date} 귀속")
        else:
            lines.append(f"세션 {s.start_at:%m-%d %H:%M} → ? (종료 없음)")
    day = svc.result.day_status.get((snap["member_id"], snap["target_date"]))
    day_txt = summary.STATUS_KO.get(day, "-") if day else "-"
    body = "".join(message_html(svc, msgs[i], labels) for i in snap["message_ids"] if i in msgs)
    who = html.escape(names.get(snap["member_id"], "?"))
    st.markdown(
        f"<div class='pc-done'><div class='pc-done-title'>✅ 처리 완료 — {who}"
        f" · {snap['target_date'] or '날짜 미정'} · {snap['types']}</div>{body}"
        f"<div style='margin-top:6px'>{'<br>'.join(lines) or '연결된 세션 없음'}"
        f"<br>이 날짜 상태: <b>{day_txt}</b></div></div>", unsafe_allow_html=True)
    undo_button(svc, snap["gkey"])


def review_list(svc, groups: dict, page_size: int | None = None, prefix: str = "") -> None:
    """검토 그룹 목록. 이번에 처리해 해결된 그룹은 같은 자리에 '처리 완료' 카드로 남긴다."""
    recent = {k: v for k, v in st.session_state.get("recent", {}).items()
              if v and k.startswith(prefix) and k not in groups}
    entries = [(k, g[0].target_date, g[0].member_id, g) for k, g in groups.items()]
    entries += [(k, v["target_date"], v["member_id"], None) for k, v in recent.items()]
    entries.sort(key=lambda e: (str(e[1]), str(e[2])))
    if not entries:
        st.success("처리할 검토 항목이 없습니다.")
        return
    n_open = len(groups)
    n_pages, page = 1, 0
    if page_size:
        n_pages = (len(entries) - 1) // page_size + 1
        page = min(st.session_state.get("review_page", 0), n_pages - 1)
        st.session_state["review_page"] = page

    def pager(where: str):
        c = st.columns([1, 3, 1])
        if c[0].button("◀ 이전", key=f"rp_prev|{where}", disabled=page == 0, width="stretch"):
            st.session_state["review_page"] = page - 1
            st.rerun()
        c[1].markdown(f"<div style='text-align:center'>{page + 1} / {n_pages} 페이지 · "
                      f"남은 검토 {n_open}개 그룹 · 이번에 처리 {len(recent)}개</div>", unsafe_allow_html=True)
        if c[2].button("다음 ▶", key=f"rp_next|{where}", disabled=page >= n_pages - 1, width="stretch"):
            st.session_state["review_page"] = page + 1
            st.rerun()

    if page_size:
        pager("top")
        shown = entries[page * page_size:(page + 1) * page_size]
    else:
        shown = entries
    for k, _, _, g in shown:
        if g is None:
            render_resolved(svc, recent[k])
        else:
            render_review(svc, k, g)
    if page_size and n_pages > 1:
        pager("bottom")
    if recent and st.button("처리 완료 카드 정리", key=f"clear_recent|{prefix}"):
        for k in recent:
            st.session_state["recent"].pop(k, None)
            st.session_state.get("undo", {}).pop(k, None)
        st.rerun()


def page_review(svc):
    show_held = st.toggle("보류 항목도 보기", value=False)
    groups: dict[str, list] = {}
    for r in open_reviews(svc, show_held):
        groups.setdefault(f"{r.member_id}~{r.target_date}", []).append(r)
    review_list(svc, groups, page_size=REVIEW_PAGE_SIZE, prefix="")


def manual_times(prayer_date: date, start_t: time, end_t: time, grace_hour: int) -> tuple[datetime, datetime]:
    """인증 날짜 + 시각 → 실제 시각. 04:00 이전 시작은 그 다음 날 새벽으로, 종료가 시작보다 이르면 다음 날로 본다."""
    start = datetime.combine(prayer_date + timedelta(days=1 if start_t.hour < grace_hour else 0), start_t)
    end = datetime.combine(start.date(), end_t)
    if end < start:          # 같은 시각이면 그대로 두어 '종료가 시작보다 늦어야' 검증에 걸리게 한다
        end += timedelta(days=1)
    return start, end


def page_manual(svc):
    """수동 기록 CRUD: 카톡 인증 없이 관리자가 직접 입력하는 기도 기록."""
    ss = st.session_state
    names = svc.member_names()
    targets = sorted(svc.targets(), key=lambda i: names.get(i, ""))
    if not targets:
        st.info("대상 참여자가 없습니다. '참여자 설정'에서 대상자를 선택해 주세요.")
        return
    grace = svc.get_settings().grace_hour
    dates = all_dates(svc)
    # 다른 화면(개인별 현황·수정 버튼)에서 넘어온 입력값은 위젯을 만들기 전에 채운다
    pre = ss.pop("mf_prefill", None)
    if pre:
        for k, v in pre.items():
            ss[k] = v
    ss.setdefault("mf_member", targets[0])
    ss.setdefault("mf_date", dates[-1] if dates else date.today())
    ss.setdefault("mf_start", time(21, 0))
    ss.setdefault("mf_end", time(21, 30))
    ss.setdefault("mf_note", "")
    editing = ss.get("manual_edit")

    st.caption("카카오톡에 인증을 올리지 못했지만 기도한 것이 확인된 경우 등에 관리자가 직접 기록합니다. "
               "수동 기록은 완료 세션으로 집계되며, 원본 대화는 바뀌지 않습니다.")
    undo = ss.get("manual_undo")
    if undo and st.button(f"↩ 방금 삭제한 기록 되돌리기 ({names.get(undo['member_id'], '?')} · {undo['prayer_date']})",
                          key="manual_undo_btn"):
        ss.pop("manual_undo")
        svc.create_manual_record(undo["member_id"], date.fromisoformat(undo["prayer_date"]),
                                 datetime.fromisoformat(undo["start_at"]), datetime.fromisoformat(undo["end_at"]),
                                 undo["note"])
        ss["toast"] = "↩ 삭제한 기록을 되돌렸습니다"
        st.rerun()

    # ---- 추가 / 수정
    st.subheader(f"기록 수정 (#{editing})" if editing else "새 기록 추가")
    with st.container(border=True):
        c = st.columns([2, 2, 1, 1])
        member = c[0].selectbox("참여자", targets, format_func=lambda i: names.get(i, str(i)), key="mf_member")
        pdate = c[1].date_input("인증 날짜", key="mf_date")
        start_t = c[2].time_input("시작", key="mf_start", step=60)
        end_t = c[3].time_input("종료", key="mf_end", step=60)
        note = st.text_input("메모 (선택)", key="mf_note", placeholder="예: 전화로 확인, 인증 누락")
        s_at, e_at = manual_times(pdate, start_t, end_t, grace)
        st.caption(f"실제 시각: **{s_at:%m/%d %H:%M} → {e_at:%m/%d %H:%M}** "
                   f"({int((e_at - s_at).total_seconds() // 60)}분) · "
                   f"{pdate}에 인증으로 귀속. {grace:02d}:00 이전 시작은 다음 날 새벽으로 봅니다.")
        b = st.columns([1, 1, 4])
        if b[0].button("수정 저장" if editing else "추가", type="primary", width="stretch"):
            try:
                if editing:
                    svc.update_manual_record(editing, member, pdate, s_at, e_at, note.strip())
                    msg = f"✏️ 수동 기록 #{editing} 수정"
                else:
                    rid = svc.create_manual_record(member, pdate, s_at, e_at, note.strip())
                    msg = f"✅ 수동 기록 #{rid} 추가"
            except ValueError as e:
                st.error(str(e))
            else:
                day = svc.result.day_status.get((member, pdate))
                ss["toast"] = (f"{msg} — {names.get(member)} {pdate} 상태: "
                               f"{summary.STATUS_KO.get(day, '-') if day else '추적 범위 밖'}")
                ss["manual_highlight"] = editing or rid
                ss.pop("manual_edit", None)
                ss["mf_prefill"] = {"mf_note": ""}
                st.rerun()
        if editing and b[1].button("취소", width="stretch"):
            ss.pop("manual_edit", None)
            ss["mf_prefill"] = {"mf_note": ""}
            st.rerun()

    # ---- 목록
    st.subheader("수동 기록 목록")
    who = st.selectbox("참여자 필터", [None, *targets], format_func=lambda i: "전체" if i is None else names.get(i),
                       key="manual_filter")
    records = svc.manual_records(who)
    if not records:
        st.caption("수동 기록이 없습니다.")
        return
    hl = ss.pop("manual_highlight", None)
    head = st.columns([1.2, 1.2, 2.2, 1, 2.4, 0.8, 0.8])
    for col, t in zip(head, ["인증 날짜", "참여자", "시각", "시간", "메모"]):
        col.markdown(f"**{t}**")
    for r in records:
        cols = st.columns([1.2, 1.2, 2.2, 1, 2.4, 0.8, 0.8])
        mark = "pc-msg pc-admin pc-flash" if r.id == hl else "pc-msg"
        cols[0].markdown(f"<div class='{mark}'>{r.prayer_date:%m/%d}({WEEKDAYS[(r.prayer_date.weekday() + 1) % 7]})"
                         f"</div>", unsafe_allow_html=True)
        cols[1].write(names.get(r.member_id, str(r.member_id)))
        cols[2].write(f"{r.start_at:%m/%d %H:%M} → {r.end_at:%H:%M}")
        cols[3].write(f"{int((r.end_at - r.start_at).total_seconds() // 60)}분")
        cols[4].write(r.note or "—")
        if cols[5].button("수정", key=f"medit|{r.id}", width="stretch"):
            ss["manual_edit"] = r.id
            ss["mf_prefill"] = {"mf_member": r.member_id, "mf_date": r.prayer_date, "mf_start": r.start_at.time(),
                                "mf_end": r.end_at.time(), "mf_note": r.note}
            st.rerun()
        with cols[6].popover("삭제", width="stretch"):
            st.write(f"{names.get(r.member_id)} · {r.prayer_date} 기록을 삭제할까요?")
            if st.button("삭제", key=f"mdel|{r.id}", type="primary"):
                prev = svc.delete_manual_record(r.id)
                ss["manual_undo"] = prev
                if ss.get("manual_edit") == r.id:
                    ss.pop("manual_edit")
                ss["toast"] = f"🗑 수동 기록 #{r.id} 삭제"
                st.rerun()


def page_messages(svc):
    members = svc.members()
    if not members:
        st.info("참여자가 없습니다. 먼저 파일을 업로드해 주세요.")
        return
    opts = {f"{m['display_name']} ({m['message_count']})": m["id"] for m in members}
    mid = opts[st.selectbox("참여자", list(opts))]
    q = st.text_input("검색(본문)")
    msgs = [m for m in svc.load_messages() if m.member_id == mid and (not q or q in m.raw_text)]
    labels = svc.decisions().labels
    rows = []
    for m in msgs:
        e = svc.result.events.get(m.id)
        rows.append({"시각": m.sent_at.strftime("%Y-%m-%d %H:%M"), "본문": m.raw_text,
                     "판정": e.event_type.value if e else "(대상 아님)",
                     "신뢰도": e.confidence.value if e else "", "규칙": e.matched_rule if e else "",
                     "관리자 지정": labels[m.id].value if m.id in labels else ""})
    st.caption(f"{len(rows)}건")
    show_table(rows)
    if msgs:
        st.subheader("관리자 판정 지정/해제")
        pick = st.selectbox("메시지 선택 (최근 200건)", msgs[-200:][::-1],
                            format_func=lambda m: f"{m.sent_at:%m-%d %H:%M} {m.raw_text[:40]}")
        st.markdown(message_html(svc, pick, labels), unsafe_allow_html=True)
        cur = labels.get(pick.id)
        c = st.columns(5)
        for col, et in zip(c, (EventType.START, EventType.END, EventType.OTHER)):
            on = cur == et
            if col.button(f"✓ {et.value}" if on else f"{et.value}로 지정", key=f"mm|{et.value}",
                          type="primary" if on else "secondary", disabled=on):
                act(svc, f"✅ {pick.sent_at:%m-%d %H:%M} 메시지를 {ET_KO[et]}로 지정",
                    lambda: svc.label_message(pick.id, et), touched=(pick.id,))
        if c[3].button("지정 해제", key="mm|clear", disabled=cur is None):
            act(svc, f"↩ {pick.sent_at:%m-%d %H:%M} 지정 해제", lambda: svc.label_message(pick.id, None),
                touched=(pick.id,))
    st.subheader("관리자 연결")
    links = svc.decisions().links
    if not links:
        st.caption("관리자가 만든 연결이 없습니다.")
    all_msgs = svc.messages_by_id()
    for a, b in links:
        ma, mb = all_msgs.get(a), all_msgs.get(b)
        cc = st.columns([6, 1])
        cc[0].markdown(f"{ma.sent_at if ma else a} → {mb.sent_at if mb else b}  ({ma.sender_raw if ma else ''})")
        if cc[1].button("연결 해제", key=f"unlink|{a}"):
            svc.unlink(a)
            st.rerun()


def tracking_start_input(svc, key: str, label: str = "저장") -> None:
    """추적 시작일 지정. 이 날짜부터 집계하고, 하루 전부터의 대화만 저장한다."""
    s = svc.get_settings()
    c = st.columns([2, 1, 4])
    d = c[0].date_input("추적 시작일", value=s.tracking_start_date or date.today(), key=f"tsd|{key}")
    if c[1].button(label, key=f"tsd_save|{key}", type="primary") and d != s.tracking_start_date:
        svc.save_settings(s.model_copy(update={"tracking_start_date": d}))
        st.rerun()
    c[2].caption("이 날짜부터 인증을 집계합니다. 원본 대화는 개인정보 보호를 위해 이 날짜 하루 전부터만 저장합니다.")


def page_upload(svc):
    st.info("카카오톡 PC에서 **전체 기간 대화 내보내기** 파일(.txt)을 그대로 올려 주세요. "
            "매번 전체 파일을 올려도 이미 반영된 메시지는 건너뛰고 새 메시지만 추가됩니다.")
    s = svc.get_settings()
    if s.tracking_start_date is None:
        st.warning("먼저 **추적 시작일**을 정해 주세요. 정하기 전에는 업로드할 수 없습니다.")
        tracking_start_input(svc, "upload", "시작일 저장")
        return
    st.caption(f"추적 시작일: **{s.tracking_start_date}** · 저장 범위: {svc.storage_cutoff():%Y-%m-%d} 이후 "
               "(변경은 '설정'에서)")
    files = st.file_uploader("카카오톡 대화 내보내기(.txt)", type=["txt"], accept_multiple_files=True)
    if files and st.button("가져오기", type="primary"):
        for f in files:
            rep = svc.import_file(f.name, f.getvalue())
            if rep.status == "DUPLICATE_FILE":
                st.warning(f"{rep.filename}: 이미 업로드된 파일입니다(중복 파일).")
            elif rep.status == "EMPTY":
                st.error(f"{rep.filename}: 읽을 수 있는 메시지가 없습니다.")
            elif rep.status == "BEFORE_START":
                st.warning(f"{rep.filename}: 모든 메시지({rep.total_messages}건)가 저장 범위 이전입니다.")
            else:
                saved = f" · 내보내기 시각 {rep.saved_at:%Y-%m-%d %H:%M}" if rep.saved_at else ""
                st.success(f"{rep.filename}: 전체 {rep.total_messages}건 중 새 메시지 {rep.new_messages}건 저장 "
                           f"(시작일 이전이라 건너뜀 {rep.skipped_before_start}건{saved})")
                if rep.new_senders:
                    st.info("새 참여자: " + ", ".join(rep.new_senders) + " — '참여자 설정'에서 대상자를 지정해 주세요.")
            if rep.issues:
                with st.expander(f"{rep.filename} 파싱 경고 {len(rep.issues)}건"):
                    st.dataframe(pd.DataFrame(rep.issues), hide_index=True, width="stretch")
    st.subheader("업로드된 파일")
    sf = svc.source_files()
    if sf:
        df = pd.DataFrame(sf)[["filename", "imported_at", "message_count", "new_message_count", "skipped_count",
                               "coverage_start", "coverage_end", "parse_status"]]
        df.columns = ["파일명", "업로드 시각", "메시지 수", "새 메시지 수", "건너뛴 메시지",
                      "수집 범위 시작", "수집 범위 끝(내보내기 시각)", "상태"]
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.caption("업로드된 파일이 없습니다.")
    st.subheader("데이터 관리")
    st.write(f"DB 파일 위치: `{svc.db_path}`")
    ok = st.checkbox("모든 원본 데이터를 삭제하는 것에 동의합니다(되돌릴 수 없음)")
    if st.button("모든 원본 데이터 삭제", disabled=not ok):
        svc.delete_all_data()
        st.rerun()


def page_members(svc):
    members = svc.members()
    if not members:
        st.info("참여자가 없습니다. 먼저 파일을 업로드해 주세요.")
        return
    st.caption("대상자는 자동으로 선택되지 않습니다. 직접 체크해 주세요.")
    df = pd.DataFrame([{"id": m["id"], "대상": bool(m["is_target"]), "이름": m["display_name"],
                        "별칭": m["aliases"], "메시지 수": m["message_count"]} for m in members])
    edited = st.data_editor(df, hide_index=True, width="stretch",
                            disabled=["id", "이름", "별칭", "메시지 수"], key="member_editor")
    chosen = {int(r["id"]) for _, r in edited.iterrows() if r["대상"]}
    if len(chosen) != 10:
        st.warning(f"현재 선택된 대상자는 {len(chosen)}명입니다(보통 10명). 그대로 저장할 수도 있습니다.")
    if st.button("대상자 저장", type="primary"):
        svc.set_targets(chosen)
        st.rerun()
    names = {m["id"]: m["display_name"] for m in members}
    st.subheader("이름 변경")
    c = st.columns([3, 3, 1])
    who = c[0].selectbox("참여자", list(names), format_func=names.get, key="rn_who")
    new = c[1].text_input("새 이름", key="rn_new")
    if c[2].button("변경") and new.strip():
        svc.rename_member(who, new.strip())
        st.rerun()
    st.subheader("참여자 병합 (닉네임 변경 대응)")
    c = st.columns([3, 3, 1])
    src = c[0].selectbox("병합할 참여자(A, 사라짐)", list(names), format_func=names.get, key="mg_a")
    dst = c[1].selectbox("합칠 대상(B, 유지)", list(names), format_func=names.get, key="mg_b")
    if c[2].button("병합"):
        if src == dst:
            st.error("서로 다른 참여자를 선택해 주세요.")
        else:
            svc.merge_member(src, dst)
            st.rerun()


def page_settings(svc):
    s = svc.get_settings()
    st.subheader("추적 시작일")
    tracking_start_input(svc, "settings")
    st.caption("이 날짜 이전으로 귀속될 새벽 인증은 집계에서 제외됩니다. 시작일을 앞당겼다면 같은 전체 내보내기 "
               "파일을 다시 올려 주세요 — 모자란 앞부분만 채워집니다.")
    n_old = svc.count_before_cutoff()
    if n_old:
        st.warning(f"저장 범위 이전의 원본 메시지 {n_old}건이 남아 있습니다(시작일을 늦춘 경우).")
        ok = st.checkbox("저장 범위 이전 원본 메시지와 그 판정을 삭제하는 것에 동의합니다", key="purge_ok")
        if st.button("범위 이전 원본 삭제", disabled=not ok):
            svc.purge_before_cutoff()
            st.rerun()
    st.subheader("판정 규칙")
    tsd = s.tracking_start_date
    grace = st.number_input("새벽 유예 시각(grace_hour, 시)", 0, 12, s.grace_hour)
    mx = st.number_input("세션 최대 길이(시간)", 0.5, 24.0, float(s.max_session_hours), step=0.5)
    a1 = st.checkbox("진행 중 세션이 있을 때 단독 '마칩니다' 자동 확정", value=s.auto_confirm_bare_end_in_session)
    a2 = st.checkbox("단독 '시작합니다' 자동 확정", value=s.auto_confirm_bare_start)
    a5 = st.checkbox("단독 '기도합니다' 뒤에 같은 사람의 '마칩니다'가 오면 시작으로 자동 확정",
                     value=s.auto_confirm_pray_start_before_end)
    a3 = st.checkbox("검증된 오타/구어체를 정상 문맥에서 자동 확정", value=s.auto_confirm_typo_in_context)
    a4 = st.checkbox("문장 끝에 붙은 인증('…가지고 기도 시작합니다')을 정상 문맥에서 자동 확정",
                     value=s.auto_confirm_suffix_in_context)
    fz = st.slider("퍼지 매칭 최소 유사도", 0, 100, s.fuzzy_threshold)
    if st.button("설정 저장", type="primary"):
        svc.save_settings(s.model_copy(update=dict(
            tracking_start_date=tsd, grace_hour=int(grace), max_session_hours=float(mx),
            auto_confirm_bare_end_in_session=a1, auto_confirm_bare_start=a2, auto_confirm_pray_start_before_end=a5,
            auto_confirm_typo_in_context=a3, auto_confirm_suffix_in_context=a4, fuzzy_threshold=int(fz))))
        st.success("저장하고 다시 계산했습니다.")


def page_export(svc):
    dates = all_dates(svc)
    if not dates:
        st.info("내보낼 데이터가 없습니다.")
        return
    rng = st.date_input("기간", value=(dates[0], dates[-1]), min_value=dates[0], max_value=dates[-1])
    if not isinstance(rng, (tuple, list)) or len(rng) != 2:
        st.info("시작일과 종료일을 모두 선택해 주세요.")
        return
    a, b = rng
    table = summary.daily_status_table(svc, a, b)
    detail = summary.session_details(svc, a, b)
    tag = f"{a:%Y%m%d}_{b:%Y%m%d}"
    c = st.columns(3)
    c[0].download_button("날짜별 현황표 CSV", export.to_csv_bytes(table), f"현황표_{tag}.csv", "text/csv")
    c[1].download_button("세션 상세 CSV", export.to_csv_bytes(detail), f"세션상세_{tag}.csv", "text/csv")
    c[2].download_button("Excel (두 시트)", export.to_excel_bytes({"날짜별 현황표": table, "세션 상세 내역": detail}),
                         f"기도인증_{tag}.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.subheader("PDF 보고서 (하루 1페이지)")
    st.caption("위에서 고른 기간의 날짜마다 같은 템플릿을 적용합니다: 이름 · 인증 여부 · 세션 시작 · 종료 · 지속 시간.")
    n_days = (b - a).days + 1
    c = st.columns([1, 1, 2])
    if c[0].button(f"PDF 만들기 ({n_days}페이지)", type="primary"):
        with st.spinner("PDF를 만드는 중..."):
            st.session_state["pdf_bytes"] = (tag, pdf.build_pdf(svc, a, b))
    made = st.session_state.get("pdf_bytes")
    if made and made[0] == tag:
        c[1].download_button("PDF 받기", made[1], f"기도인증_{tag}.pdf", "application/pdf")
    pv = st.select_slider("미리볼 날짜", options=[a + timedelta(days=i) for i in range(n_days)], value=b,
                          format_func=lambda d: f"{d:%m/%d}({WEEKDAYS[(d.weekday() + 1) % 7]})")
    png = pdf.day_png(svc, pv)
    st.download_button(f"{pv} 이미지(PNG) 받기", png, f"기도인증_{pv:%Y%m%d}.png", "image/png")
    st.image(png, width=620)

    st.subheader("미리보기")
    show_table(table)


def page_audit(svc):
    log = svc.audit_log()
    if log:
        st.dataframe(pd.DataFrame(log), hide_index=True, width="stretch")
    else:
        st.info("변경 이력이 없습니다.")


# ------------------------------------------------------------------ 업데이트
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def latest_release() -> dict | None:
    """앱을 켤 때 새 버전 알림용(실패하면 조용히 None). 6시간 동안 다시 묻지 않는다."""
    if updater.check_disabled():
        return None
    try:
        return updater.info_dict(updater.fetch_latest(timeout=3))
    except updater.UpdateError:
        return None


def restart_notice(version: str) -> None:
    st.success(f"**v{version} 업데이트 준비를 마쳤습니다. 프로그램을 다시 실행해 주세요.**\n\n"
               "1. 이 브라우저 탭과 **검은 창**을 닫습니다.\n"
               "2. 프로그램 폴더의 **run.bat**을 다시 더블클릭합니다.\n\n"
               "다시 실행할 때 새 버전이 적용됩니다. 기록(data 폴더)은 바뀌지 않고, 적용 직전에 "
               "`data\\backup` 폴더에 사본이 하나 더 저장됩니다.")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def changelog() -> list[dict]:
    return updater.fetch_changelog()   # 실패(예외)는 캐시하지 않으므로 인터넷이 돌아오면 다음에 다시 시도한다


def changelog_section() -> None:
    """버전별 바뀐 점(GitHub Release 설명 모음). 6시간 동안 다시 묻지 않는다."""
    st.divider()
    st.subheader("버전별 바뀐 점")
    if updater.check_disabled():
        st.caption("업데이트 확인이 꺼져 있어 표시하지 않습니다.")
        return
    try:
        with st.spinner("불러오는 중..."):
            items = changelog()
    except updater.UpdateError as e:
        st.caption(str(e))
        return
    if not items:
        st.caption("아직 공개된 버전이 없습니다.")
        return
    for i, it in enumerate(items):
        mark = " (사용 중)" if it["version"] == __version__ else ""
        title = f"v{it['version']}{mark}" + (f" — {it['published_at']}" if it["published_at"] else "")
        with st.expander(title, expanded=i == 0):
            body = re.sub(r"^#+\s*바뀐 점\s*\n", "", it["notes"]).strip()   # 접는 칸 제목과 겹치는 머리말
            st.markdown(body or "(설명 없음)")


def page_update(svc):
    update_status()
    changelog_section()


def update_status():
    root = ROOT
    st.write(f"현재 버전: **v{__version__}**")
    res = updater.last_result(root)
    if res and not res.get("ok"):
        st.error(f"지난 업데이트(v{res.get('version')})를 적용하지 못해 이전 버전으로 실행 중입니다.\n\n"
                 f"{res.get('message', '')}\n\n아래에서 다시 시도할 수 있습니다. 기록은 그대로입니다.")
    elif res and res.get("ok") and res.get("version") == __version__:
        st.caption(f"{res.get('at', '')[:16].replace('T', ' ')}에 v{res.get('from_version')} → "
                   f"v{res.get('version')} 업데이트를 적용했습니다.")

    if updater.is_dev_checkout(root):
        st.info("개발 폴더에서 실행 중이라 업데이트를 받지 않습니다. (배포한 프로그램 폴더에서만 동작합니다)")
        return

    ready = updater.prepared(root)
    if ready:
        restart_notice(ready["version"])
        if st.button("준비한 업데이트 취소"):
            updater.cancel(root)
            st.rerun()
        return

    if st.session_state.pop("update_recheck", False) or "update_latest" not in st.session_state:
        with st.spinner("새 버전을 확인하는 중..."):
            try:
                st.session_state["update_latest"] = updater.info_dict(updater.fetch_latest())
                st.session_state["update_error"] = None
            except updater.UpdateError as e:
                st.session_state["update_latest"], st.session_state["update_error"] = None, str(e)
        latest_release.clear()
        changelog.clear()
    latest, err = st.session_state.get("update_latest"), st.session_state.get("update_error")
    if err:
        st.warning(err)
    elif latest and updater.is_newer(latest["version"], __version__):
        st.subheader(f"새 버전 v{latest['version']}")
        if latest.get("published_at"):
            st.caption(f"공개: {latest['published_at'][:10]}")
        notes = updater.strip_checksum(latest.get("notes", ""))
        if notes:
            with st.container(border=True):
                st.markdown(notes)
        st.caption("[업데이트]를 누르면 새 버전을 내려받아 준비합니다. 실제 적용은 프로그램을 다시 실행할 때 됩니다. "
                   "기록(data 폴더)은 바뀌지 않습니다.")
        if st.button("업데이트", type="primary"):
            info = updater.ReleaseInfo(**latest)
            bar = st.progress(0.0, text="내려받는 중...")

            def prog(done: int, total: int) -> None:
                if total:
                    bar.progress(min(done / total, 1.0), text=f"내려받는 중... {done // 1024:,} / {total // 1024:,} KB")

            try:
                updater.prepare(root, info, __version__, progress=prog)
            except updater.UpdateError as e:
                bar.empty()
                st.error(str(e))
            else:
                st.rerun()
    elif latest:
        st.success("최신 버전을 사용하고 있습니다.")
    if st.button("다시 확인"):
        st.session_state["update_recheck"] = True
        st.rerun()


def update_sidebar() -> None:
    """준비된 업데이트나 새 버전이 있으면 사이드바에 알리고 [업데이트] 버튼을 보여 준다."""
    if updater.is_dev_checkout(ROOT):
        return
    ready = updater.prepared(ROOT)
    if ready:
        st.sidebar.success(f"v{ready['version']} 업데이트 준비 완료 — 프로그램을 다시 실행하면 적용됩니다.")
        return
    latest = latest_release()
    if latest and updater.is_newer(latest["version"], __version__):
        st.sidebar.info(f"새 버전 **v{latest['version']}**이 있습니다.")
        if st.sidebar.button("업데이트", type="primary", width="stretch", key="sb_update"):
            go("update", update_latest=latest, update_error=None)


# ------------------------------------------------------------------ 메인
def main():
    svc = get_service()
    n = len(open_reviews(svc))
    pages = {
        "dashboard": ("대시보드", page_dashboard),
        "person": ("개인별 현황", page_person),
        "review": (f"검토 ({n})" if n else "검토", page_review),
        "manual": ("수동 기록", page_manual),
        "messages": ("메시지/판정", page_messages),
        "upload": ("업로드", page_upload),
        "members": ("참여자 설정", page_members),
        "settings": ("설정", page_settings),
        "export": ("내보내기", page_export),
        "audit": ("변경 이력", page_audit),
        "update": ("업데이트", page_update),
    }
    st.sidebar.title("기도 인증 현황")
    st.sidebar.caption(f"버전 {__version__}")
    update_sidebar()
    # 메뉴: 글자가 크고 누르기 쉬운 버튼(현재 페이지는 강조). 라벨(검토 건수)이 바뀌어도 key는 그대로다.
    # on_click은 화면을 다시 그리기 전에 실행되므로, 누른 즉시 강조 표시도 맞게 나온다.
    cur = st.session_state.get("page", "dashboard")
    key = cur if cur in pages else "dashboard"
    st.session_state["page"] = key
    nav = st.sidebar.container(key="pc_nav")
    for k, (label, _) in pages.items():
        nav.button(label, key=f"nav|{k}", width="stretch", type="primary" if k == key else "secondary",
                   on_click=st.session_state.__setitem__, args=("page", k))
    if st.session_state.get("last_page") != key:
        # 페이지를 옮기면 '처리 완료' 카드와 되돌리기 기록을 정리한다
        st.session_state["last_page"] = key
        st.session_state["recent"], st.session_state["undo"] = {}, {}
    st.markdown(FEEDBACK_CSS, unsafe_allow_html=True)
    toast = st.session_state.pop("toast", None)
    if toast:
        st.toast(toast)
    st.title(pages[key][0].split(" (")[0])
    pages[key][1](svc)


main()
