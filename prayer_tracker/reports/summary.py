"""보고용 순수 함수. PrayerService / AnalysisResult 위에서만 동작한다."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from prayer_tracker.models import DateSource, DayStatus, SessionStatus

STATUS_KO = {
    DayStatus.COMPLETE: "완료",
    DayStatus.INCOMPLETE: "미완료",
    DayStatus.MISSING: "미인증",
    DayStatus.PENDING_REVIEW: "검토 대기",
    DayStatus.PENDING_DATA: "데이터 확인 대기",
}
SESSION_STATUS_KO = {
    SessionStatus.COMPLETE: "완료",
    SessionStatus.IN_PROGRESS: "종료 대기",
    SessionStatus.INCOMPLETE: "종료 누락",
}
DATE_SOURCE_KO = {
    DateSource.START_DATE: "시작일 기준",
    DateSource.PREV_DAY: "새벽 시작 → 전날 귀속",
    DateSource.SAME_DAY: "새벽 시작 → 당일 귀속",
    DateSource.ADMIN: "관리자 지정",
    DateSource.PENDING: "판단 불가(검토 필요)",
    DateSource.OUT_OF_RANGE: "추적 시작일 이전(집계 제외)",
}


def fmt_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}시간 {m}분" if h else f"{m}분"


def _t(dt: datetime | None) -> str:
    return dt.strftime("%H:%M") if dt else ""


def _dtstr(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def _open_review_set(service) -> set[tuple[int, date]]:
    return {(r.member_id, r.target_date) for r in service.result.reviews
            if r.status in ("OPEN", "HELD")}


def _targets(service) -> list[tuple[int, str]]:
    names = service.member_names()
    return sorted(((i, names.get(i, str(i))) for i in service.targets()), key=lambda x: x[1])


def _sessions_by_key(service) -> dict[tuple[int, date], list]:
    out = defaultdict(list)
    for s in service.result.sessions:
        if s.prayer_date and s.date_source != DateSource.OUT_OF_RANGE:
            out[(s.member_id, s.prayer_date)].append(s)
    for v in out.values():
        v.sort(key=lambda s: s.start_at or s.end_at or datetime.min)
    return out


def _fmt_times(vals: list[str]) -> str:
    vals = [v for v in vals]
    if not vals:
        return ""
    return vals[0] if len(vals) == 1 else f"{vals[0]} 외 {len(vals) - 1}건"


def day_overview(service, d: date) -> list[dict]:
    res = service.result
    sess = _sessions_by_key(service)
    reviews = _open_review_set(service)
    rows = []
    for mid, name in _targets(service):
        status = res.day_status.get((mid, d))
        ss = sess.get((mid, d), [])
        complete = [s for s in ss if s.status == SessionStatus.COMPLETE]
        total = sum(s.duration_seconds or 0 for s in complete)
        first = ss[0] if ss else None
        rows.append({
            "이름": name,
            "인증 상태": STATUS_KO.get(status, "") if status else "",
            "시작 시각": _fmt_times([_t(s.start_at) for s in ss if s.start_at]),
            "종료 시각": _fmt_times([_t(s.end_at) for s in ss if s.end_at]),
            "세션 수": len(ss),
            "총 기도 시간": fmt_duration(total) if complete else "",
            "실제 시작 날짜": first.start_at.date().isoformat() if first and first.start_at else "",
            "인증 귀속 날짜": d.isoformat() if ss else "",
            "귀속 방식": ", ".join(dict.fromkeys(DATE_SOURCE_KO.get(s.date_source, "") for s in ss if s.date_source)),
            "검토 필요": "예" if (mid, d) in reviews else "",
        })
    return rows


def day_summary(service, d: date) -> dict:
    counts = {label: 0 for label in STATUS_KO.values()}
    for (mid, day), st in service.result.day_status.items():
        if day == d:
            counts[STATUS_KO[st]] += 1
    counts["마지막 반영 시각"] = service.last_import_at() or ""
    return counts


def session_details(service, start: date | None = None, end: date | None = None,
                    include_out_of_range: bool = False, member_id: int | None = None) -> list[dict]:
    names = service.member_names()
    reviews = _open_review_set(service)
    rows = []
    for s in service.result.sessions:
        if s.date_source == DateSource.OUT_OF_RANGE and not include_out_of_range:
            continue
        if member_id is not None and s.member_id != member_id:
            continue
        d = s.prayer_date
        if d and ((start and d < start) or (end and d > end)):
            continue
        if d is None and (start or end):
            continue
        status = service.result.day_status.get((s.member_id, d)) if d else None
        rows.append({
            "날짜": d.isoformat() if d else "",
            "참여자 이름": names.get(s.member_id, str(s.member_id)),
            "인증 상태": STATUS_KO.get(status, "") if status else "",
            "세션 상태": SESSION_STATUS_KO.get(s.status, s.status.value),
            "시작 시각": _dtstr(s.start_at),
            "종료 시각": _dtstr(s.end_at),
            "기도 시간": fmt_duration(s.duration_seconds),
            "날짜 귀속 여부": DATE_SOURCE_KO.get(s.date_source, "") if s.date_source else "",
            "입력 방식": "수동 기록" if s.manual_id is not None else "관리자 연결" if s.manual else "자동",
            "검토 여부": "검토 필요" if d and (s.member_id, d) in reviews else "",
        })
    rows.sort(key=lambda r: (r["날짜"], r["참여자 이름"], r["시작 시각"]))
    return rows


def daily_matrix(service, start: date | None = None, end: date | None = None) -> list[dict]:
    """참여자(행) × 날짜(열) 상태표."""
    ds = service.result.day_status
    dates = sorted({d for (_, d) in ds if (not start or d >= start) and (not end or d <= end)})
    rows = []
    for mid, name in _targets(service):
        row = {"이름": name}
        for d in dates:
            st = ds.get((mid, d))
            row[d.isoformat()] = STATUS_KO.get(st, "") if st else ""
        rows.append(row)
    return rows


def daily_status_table(service, start: date | None = None, end: date | None = None) -> list[dict]:
    """날짜별 현황표(내보내기용): 날짜 × 참여자 한 줄씩."""
    rows = []
    dates = sorted({d for (_, d) in service.result.day_status
                    if (not start or d >= start) and (not end or d <= end)})
    for d in dates:
        for r in day_overview(service, d):
            rows.append({"날짜": d.isoformat(), "참여자 이름": r["이름"], "인증 상태": r["인증 상태"],
                         "시작 시각": r["시작 시각"], "종료 시각": r["종료 시각"],
                         "기도 시간": r["총 기도 시간"], "날짜 귀속 여부": r["귀속 방식"],
                         "검토 여부": r["검토 필요"]})
    return rows


def person_summary(service, member_id: int) -> dict:
    """개인별 요약. 완료율 = 완료일 / 확정된 날(검토 대기·데이터 확인 대기 제외)."""
    res = service.result
    statuses = {d: st for (m, d), st in res.day_status.items() if m == member_id}
    c = {k: sum(v == k for v in statuses.values()) for k in DayStatus}
    decided = c[DayStatus.COMPLETE] + c[DayStatus.INCOMPLETE] + c[DayStatus.MISSING]
    durs = [s.duration_seconds for s in res.sessions
            if s.member_id == member_id and s.duration_seconds is not None and s.prayer_date
            and s.date_source != DateSource.OUT_OF_RANGE]
    return {
        "완료율": c[DayStatus.COMPLETE] / decided if decided else None,
        "완료일": c[DayStatus.COMPLETE], "확정된 날": decided,
        "미인증 일수": c[DayStatus.MISSING], "미완료 일수": c[DayStatus.INCOMPLETE],
        "평균 기도 시간": fmt_duration(sum(durs) // len(durs)) if durs else "",
        "총 기도 시간": fmt_duration(sum(durs)) if durs else "",
        "검토 대기": sum(1 for r in res.reviews if r.member_id == member_id and r.status in ("OPEN", "HELD")),
    }


def person_days(service, member_id: int, statuses: tuple[DayStatus, ...]) -> list[dict]:
    """해당 상태인 날짜 목록(예: 미인증·미완료)."""
    return [{"날짜": d.isoformat(), "요일": "월화수목금토일"[d.weekday()], "상태": STATUS_KO[st]}
            for (m, d), st in sorted(service.result.day_status.items(), key=lambda x: x[0][1])
            if m == member_id and st in statuses]
