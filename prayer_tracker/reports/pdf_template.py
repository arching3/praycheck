"""일자별 보고서 템플릿: DayReport 하나를 A4 한 장 이미지로 그린다.
디자인을 바꾸려면 DayReportTemplate 값만 고치면 된다."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from prayer_tracker.models import DayStatus
from prayer_tracker.reports.day_report import DayReport

WEEKDAY_KO = "월화수목금토일"
FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/nanum"), Path("/Library/Fonts")]
FONT_CANDIDATES = {
    "regular": ["malgun.ttf", "NanumGothic.ttf", "AppleSDGothicNeo.ttc"],
    "bold": ["malgunbd.ttf", "NanumGothicBold.ttf", "AppleSDGothicNeo.ttc"],
}


def find_font(kind: str) -> str:
    for d in FONT_DIRS:
        for name in FONT_CANDIDATES[kind]:
            if (d / name).exists():
                return str(d / name)
    raise FileNotFoundError("한글 글꼴(맑은 고딕 또는 나눔고딕)을 찾을 수 없습니다. "
                            "DayReportTemplate.font_regular/font_bold에 글꼴 경로를 지정해 주세요.")


@dataclass
class DayReportTemplate:
    title: str = "기도 인증 현황"
    footnote: str = "새벽 04:00 이전에 시작한 기도는 규칙에 따라 전날 인증으로 귀속될 수 있습니다. '수동' = 관리자 입력 기록"
    width: int = 1240                 # A4 @150dpi
    height: int = 1754
    dpi: int = 150
    margin: int = 90
    row_height: int = 74              # 세션 1개 기준 행 높이
    line_height: int = 40             # 세션이 여러 개일 때 추가 줄 높이
    font_regular: str | None = None   # None이면 자동 탐색
    font_bold: str | None = None
    ink: str = "#1f2328"
    muted: str = "#6b7280"
    rule: str = "#e5e7eb"
    zebra: str = "#f7f8fa"
    header_bg: str = "#eef1f5"
    accent: str = "#2e9d5b"
    status_colors: dict = field(default_factory=lambda: {
        DayStatus.COMPLETE: "#2e9d5b", DayStatus.INCOMPLETE: "#e08a1e", DayStatus.MISSING: "#d9534f",
        DayStatus.PENDING_REVIEW: "#c9a227", DayStatus.PENDING_DATA: "#8a8f98",
    })
    # (제목, 너비 비율) — 이름 / 인증 여부 / 세션 시작 / 세션 종료 / 지속 시간
    columns: list = field(default_factory=lambda: [
        ("이름", 0.22), ("인증 여부", 0.20), ("세션 시작", 0.19), ("세션 종료", 0.19), ("지속 시간", 0.20)])


class _Fonts:
    def __init__(self, t: DayReportTemplate):
        reg, bold = t.font_regular or find_font("regular"), t.font_bold or find_font("bold")
        self.f = lambda size, b=False: ImageFont.truetype(bold if b else reg, size)


def _center_text(draw, box, text, font, fill):
    x0, y0, x1, y1 = box
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    draw.text((x0 + (x1 - x0 - (r - l)) / 2 - l, y0 + (y1 - y0 - (b - t)) / 2 - t), text, font=font, fill=fill)


def _left_text(draw, x, y_mid, text, font, fill):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    draw.text((x - l, y_mid - (b - t) / 2 - t), text, font=font, fill=fill)


def render_day(report: DayReport, template: DayReportTemplate | None = None,
               page: tuple[int, int] | None = None) -> Image.Image:
    t = template or DayReportTemplate()
    F = _Fonts(t).f
    img = Image.new("RGB", (t.width, t.height), "white")
    draw = ImageDraw.Draw(img)
    m, W = t.margin, t.width - 2 * t.margin
    d = report.day

    # ---- 머리글
    draw.rectangle([0, 0, t.width, 14], fill=t.accent)
    _left_text(draw, m, 80, t.title, F(30, True), t.muted)
    _left_text(draw, m, 150, f"{d.year}년 {d.month}월 {d.day}일 {WEEKDAY_KO[d.weekday()]}요일", F(56, True), t.ink)

    # ---- 요약 칸
    y = 220
    stats = [(label, report.counts.get(label, 0), color)
             for st, color in t.status_colors.items()
             for label in [{DayStatus.COMPLETE: "완료", DayStatus.INCOMPLETE: "미완료", DayStatus.MISSING: "미인증",
                            DayStatus.PENDING_REVIEW: "검토 대기",
                            DayStatus.PENDING_DATA: "데이터 확인 대기"}[st]]]
    gap = 16
    bw = (W - gap * (len(stats) - 1)) / len(stats)
    for i, (label, n, color) in enumerate(stats):
        x0 = m + i * (bw + gap)
        draw.rounded_rectangle([x0, y, x0 + bw, y + 110], radius=14, outline=t.rule, width=2,
                               fill="white")
        draw.rounded_rectangle([x0, y, x0 + 8, y + 110], radius=4, fill=color)
        _center_text(draw, (x0, y + 8, x0 + bw, y + 62), str(n), F(44, True), color if n else t.muted)
        _center_text(draw, (x0, y + 62, x0 + bw, y + 104), label, F(22), t.muted)
    total_targets = len(report.rows)
    _left_text(draw, m, y + 140, f"대상 {total_targets}명", F(22), t.muted)

    # ---- 표
    y = 400
    xs = [m]
    for _, w in t.columns:
        xs.append(xs[-1] + W * w)
    draw.rounded_rectangle([m, y, m + W, y + 60], radius=10, fill=t.header_bg)
    for (title, _), x0, x1 in zip(t.columns, xs, xs[1:]):
        _center_text(draw, (x0, y, x1, y + 60), title, F(24, True), t.ink)
    y += 60
    for i, row in enumerate(report.rows):
        n_lines = max(1, len(row.sessions))
        h = t.row_height + (n_lines - 1) * t.line_height
        if i % 2:
            draw.rectangle([m, y, m + W, y + h], fill=t.zebra)
        draw.line([m, y + h, m + W, y + h], fill=t.rule, width=1)
        mid_y = y + h / 2
        _center_text(draw, (xs[0], y, xs[1], y + h), row.name, F(28, True), t.ink)
        color = t.status_colors.get(row.status, t.muted)
        pw, ph = 150, 44
        px = xs[1] + (xs[2] - xs[1] - pw) / 2
        draw.rounded_rectangle([px, mid_y - ph / 2, px + pw, mid_y + ph / 2], radius=22, fill=color)
        label = row.status_label if len(row.status_label) <= 5 else row.status_label.replace(" 확인", "")
        _center_text(draw, (px, mid_y - ph / 2, px + pw, mid_y + ph / 2), label, F(23, True), "white")
        if row.sessions:
            top = y + (h - n_lines * t.line_height) / 2
            for k, s in enumerate(row.sessions):
                ly = (top + k * t.line_height, top + (k + 1) * t.line_height)
                ink = t.ink if s.complete else t.status_colors[DayStatus.INCOMPLETE]
                _center_text(draw, (xs[2], *ly[:1], xs[3], ly[1]), s.start, F(26), t.ink)
                _center_text(draw, (xs[3], ly[0], xs[4], ly[1]), s.end if s.complete or s.end != "—"
                             else "종료 없음", F(26), ink)
                dur = (s.duration or "—") + (" · 수동" if s.manual else "")
                _center_text(draw, (xs[4], ly[0], xs[5], ly[1]), dur, F(26, s.complete), ink)
        else:
            for a, b in ((2, 3), (3, 4), (4, 5)):
                _center_text(draw, (xs[a], y, xs[b], y + h), "—", F(26), t.muted)
        y += h

    # ---- 바닥글
    fy = t.height - 70
    draw.line([m, fy - 30, m + W, fy - 30], fill=t.rule, width=1)
    _left_text(draw, m, fy, t.footnote, F(19), t.muted)
    right = f"생성 {report.generated_at:%Y-%m-%d %H:%M}" + (f"   ·   {page[0]} / {page[1]}" if page else "")
    l, _, r, _ = draw.textbbox((0, 0), right, font=F(19))
    _left_text(draw, m + W - (r - l), fy, right, F(19), t.muted)
    return img
