"""대시보드 위젯: 월별 날짜 버튼 달력, 기도 세션 타임라인."""
from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from prayer_tracker.models import DateSource, DayStatus, SessionStatus

WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"]
DATE_SOURCE_KO = {
    DateSource.START_DATE: "시작일", DateSource.PREV_DAY: "전날 귀속(새벽)",
    DateSource.SAME_DAY: "당일 귀속(새벽)", DateSource.ADMIN: "관리자 지정",
    DateSource.PENDING: "판단 보류", DateSource.OUT_OF_RANGE: "집계 제외",
}
SESSION_KO = {SessionStatus.COMPLETE: "완료", SessionStatus.IN_PROGRESS: "진행 중",
              SessionStatus.INCOMPLETE: "종료 누락"}
DAY_KO = {DayStatus.COMPLETE: "완료", DayStatus.INCOMPLETE: "미완료", DayStatus.MISSING: "미인증",
          DayStatus.PENDING_REVIEW: "검토 대기", DayStatus.PENDING_DATA: "데이터 대기"}


# ------------------------------------------------------------------ 달력
def _day_marker(statuses: list[DayStatus]) -> str:
    if not statuses:
        return ""
    if DayStatus.PENDING_REVIEW in statuses:
        return "🟠"
    if all(s == DayStatus.COMPLETE for s in statuses):
        return "🟢"
    if any(s in (DayStatus.MISSING, DayStatus.INCOMPLETE) for s in statuses):
        return "🔴"
    return "⚪"   # 완료 + 데이터 대기만 있음


def _shift_month(y: int, m: int, delta: int) -> tuple[int, int]:
    i = y * 12 + (m - 1) + delta
    return i // 12, i % 12 + 1


def month_calendar(dates: list[date], prefix: str, label_fn, caption: str) -> date:
    """월별 버튼 달력(공용). label_fn(d) → 버튼 글자. 데이터가 없는 날은 비활성. 선택 날짜를 반환한다.
    상태 키: {prefix}_sel(선택 날짜), {prefix}_month(표시 중인 달)."""
    ss = st.session_state
    sel_key, month_key = f"{prefix}_sel", f"{prefix}_month"
    available = set(dates)
    sel = ss.get(sel_key)
    if sel not in available:
        sel = dates[-1]
        ss[sel_key] = sel
    y, m = ss.get(month_key) or (sel.year, sel.month)
    first, last = (dates[0].year, dates[0].month), (dates[-1].year, dates[-1].month)

    nav = st.columns([1, 1, 5, 1, 1])
    if nav[0].button("◀", key=f"{prefix}_prev", disabled=(y, m) <= first, help="이전 달", width="stretch"):
        ss[month_key] = _shift_month(y, m, -1)
        st.rerun()
    nav[2].markdown(f"<h3 style='text-align:center;margin:0'>{y}년 {m}월</h3>", unsafe_allow_html=True)
    if nav[4].button("▶", key=f"{prefix}_next", disabled=(y, m) >= last, help="다음 달", width="stretch"):
        ss[month_key] = _shift_month(y, m, 1)
        st.rerun()
    if nav[1].button("최근", key=f"{prefix}_latest", help="가장 최근 날짜로", width="stretch"):
        ss[sel_key], ss[month_key] = dates[-1], (dates[-1].year, dates[-1].month)
        st.rerun()

    head = st.columns(7)
    for i, (c, wd) in enumerate(zip(head, WEEKDAYS)):
        color = "#d9534f" if i == 0 else "#4a7bd0" if i == 6 else "inherit"
        c.markdown(f"<div style='text-align:center;font-weight:600;color:{color}'>{wd}</div>",
                   unsafe_allow_html=True)
    for week in calendar.Calendar(firstweekday=6).monthdatescalendar(y, m):
        cols = st.columns(7)
        for c, d in zip(cols, week):
            if d.month != m:
                c.markdown("&nbsp;", unsafe_allow_html=True)
                continue
            if c.button(label_fn(d), key=f"{prefix}|{d}", disabled=d not in available, width="stretch",
                        type="primary" if d == sel else "secondary"):
                ss[sel_key] = d
                st.rerun()
    st.caption(caption)
    return sel


def month_picker(svc, dates: list[date]) -> date:
    """대시보드용: 날짜마다 전체 대상자의 완료 인원을 표시한다."""
    by_day: dict[date, list[DayStatus]] = {}
    for (_, d), s in svc.result.day_status.items():
        by_day.setdefault(d, []).append(s)

    def label(d: date) -> str:
        statuses = by_day.get(d, [])
        done = sum(s == DayStatus.COMPLETE for s in statuses)
        return f"{_day_marker(statuses)} {d.day}" + (f" · {done}/{len(statuses)}" if statuses else "")

    return month_calendar(dates, "cal", label,
                          "🟢 전원 완료 · 🔴 미완료/미인증 있음 · 🟠 검토 대기 있음 · ⚪ 데이터 확인 대기 · "
                          "숫자 = 완료/대상 인원")


def person_calendar(svc, member_id: int, dates: list[date]) -> date:
    """개인별: 날짜마다 그 사람의 상태와 기도 시간을 표시한다."""
    res = svc.result
    minutes: dict[date, int] = {}
    for s in res.sessions:
        if s.member_id == member_id and s.prayer_date and s.duration_seconds is not None \
                and s.date_source != DateSource.OUT_OF_RANGE:
            minutes[s.prayer_date] = minutes.get(s.prayer_date, 0) + s.duration_seconds // 60

    def label(d: date) -> str:
        st_ = res.day_status.get((member_id, d))
        if st_ is None:
            return str(d.day)
        short = {DayStatus.PENDING_REVIEW: "검토", DayStatus.PENDING_DATA: "대기"}   # 버튼 폭에 맞게
        detail = f"{minutes[d]}분" if d in minutes else short.get(st_, DAY_KO[st_])
        return f"{_day_marker([st_])} {d.day} · {detail}"

    return month_calendar(dates, f"pcal{member_id}", label,
                          "🟢 완료 · 🔴 미완료/미인증 · 🟠 검토 대기 · ⚪ 데이터 확인 대기 · 날짜를 누르면 그날 세션을 봅니다")


# ------------------------------------------------------------------ 타임라인
def timeline(svc, d: date) -> None:
    """선택 날짜에 귀속된 세션을 참여자별 가로 막대로 표시한다.
    축 범위는 귀속 창(당일 00:00 ~ 다음 날 04:00)을 기본으로 한다."""
    res = svc.result
    names = svc.member_names()
    targets = sorted(svc.targets(), key=lambda i: names.get(i, ""))
    if not targets:
        st.info("대상 참여자가 없습니다.")
        return
    label = {mid: f"{names.get(mid, mid)} · {DAY_KO.get(res.day_status.get((mid, d)), '-')}" for mid in targets}
    rows = []
    for s in res.sessions:
        if s.prayer_date != d or s.date_source == DateSource.OUT_OF_RANGE or s.member_id not in label:
            continue
        dur = s.duration_seconds
        rows.append({
            "참여자": label[s.member_id], "시작": s.start_at, "종료": s.end_at,
            "상태": SESSION_KO[s.status],
            "시작 시각": f"{s.start_at:%m/%d %H:%M}", "종료 시각": f"{s.end_at:%m/%d %H:%M}" if s.end_at else "-",
            "기도 시간": f"{dur // 60}분" if dur is not None else "-",
            "귀속 방식": DATE_SOURCE_KO.get(s.date_source, "-"),
        })
    grace = svc.get_settings().grace_hour
    day_start = datetime.combine(d, time(0))
    hi = datetime.combine(d + timedelta(days=1), time(grace))
    if st.toggle("하루 전체 보기", key="tl_full", help="끄면 세션이 있는 구간(최소 18:00~)만 확대해서 보여줍니다"):
        lo = day_start
    else:
        # 기도가 주로 저녁~새벽에 몰리므로 세션이 있는 구간으로 확대
        earliest = min((r["시작"] for r in rows), default=hi)
        lo = min(datetime.combine(d, time(18)), (earliest - timedelta(hours=1)).replace(minute=0))
    for r in rows:
        lo = min(lo, r["시작"])
        hi = max(hi, r["종료"] or r["시작"])
    df = pd.DataFrame(rows, columns=["참여자", "시작", "종료", "상태", "시작 시각", "종료 시각", "기도 시간", "귀속 방식"])

    y = alt.Y("참여자:N", sort=list(label.values()), scale=alt.Scale(domain=list(label.values())), title=None)
    x_scale = alt.Scale(domain=[lo.isoformat(), hi.isoformat()])
    color = alt.Color("상태:N", scale=alt.Scale(domain=list(SESSION_KO.values()),
                                               range=["#2e9d5b", "#8a8f98", "#e08a1e"]),
                      legend=alt.Legend(orient="top", title=None))
    tooltip = ["참여자", "상태", "시작 시각", "종료 시각", "기도 시간", "귀속 방식"]

    # 빈 행도 보이도록 참여자 축만 있는 바탕 레이어
    base = alt.Chart(pd.DataFrame({"참여자": list(label.values()), "x": [lo] * len(label)})).mark_tick(
        opacity=0).encode(x=alt.X("x:T", scale=x_scale), y=y)
    bars = alt.Chart(df[df["종료"].notna()]).mark_bar(height=16, cornerRadius=3).encode(
        x=alt.X("시작:T", scale=x_scale, axis=alt.Axis(format="%H:%M", title=None, tickCount=12)),
        x2="종료:T", y=y, color=color, tooltip=tooltip)
    starts_only = alt.Chart(df[df["종료"].isna()]).mark_point(shape="triangle-right", size=160, filled=True).encode(
        x=alt.X("시작:T", scale=x_scale), y=y, color=color, tooltip=tooltip)
    next_day = d + timedelta(days=1)
    marks = pd.DataFrame({"t": [datetime.combine(next_day, time(0)), datetime.combine(next_day, time(grace))],
                          "이름": ["자정", f"{grace:02d}:00 귀속 경계"]})
    rules = alt.Chart(marks).mark_rule(strokeDash=[4, 4], color="#999").encode(x=alt.X("t:T", scale=x_scale))
    rule_text = alt.Chart(marks).mark_text(align="right", dx=-4, dy=-6, color="#999", fontSize=11).encode(
        x=alt.X("t:T", scale=x_scale), text="이름:N", y=alt.value(0))

    chart = alt.layer(base, rules, rule_text, bars, starts_only).properties(height=34 * len(label) + 30)
    st.altair_chart(chart, width="stretch")
    if df.empty:
        st.caption("이 날짜에 귀속된 세션이 없습니다.")
    else:
        st.caption("막대 = 시작~종료, ▶ = 시작만 확인됨. 막대에 마우스를 올리면 상세 정보가 보입니다. "
                   "새벽(다음 날 04:00 이전) 세션도 이 날짜에 귀속되었다면 함께 표시됩니다.")
