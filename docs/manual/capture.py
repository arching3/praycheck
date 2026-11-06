"""사용 설명서용 Streamlit 화면 캡처. 데모 대화(가상 인물)로 앱을 띄우고 실제 사용 순서대로 클릭하며 찍는다.

필요: pip install playwright (브라우저는 설치된 Edge를 사용)
사용: python docs/manual/capture.py <작업 폴더>
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from prayer_tracker.service import PrayerService  # noqa: E402

PORT = 8613
TARGETS = ["김하늘", "이도윤", "박서준", "최유나", "정민재", "강서연", "조은우", "윤지아", "장하람", "임태오"]


def main(work: Path) -> None:
    img = ROOT / "docs" / "manual" / "images"
    img.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    chat = work / "하모니_대화.txt"
    subprocess.run([sys.executable, str(ROOT / "docs" / "manual" / "demo_chat.py"), str(chat)], check=True)
    db = work / "demo.db"
    if db.exists():
        db.unlink()
    PrayerService(db)   # 빈 DB

    env = {**os.environ, "PRAYER_TRACKER_DB": str(db), "PYTHONIOENCODING": "utf-8"}
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "prayer_tracker" / "ui" / "app.py"),
         "--server.headless", "true", "--server.port", str(PORT), "--theme.base", "light",
         "--browser.gatherUsageStats", "false"], env=env, cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5,
                                    locale="ko-KR")

            def idle(extra=600):
                page.wait_for_timeout(400)
                for _ in range(60):   # 실행 중 표시가 사라질 때까지
                    if not page.locator('[data-testid="stStatusWidget"]').is_visible():
                        break
                    page.wait_for_timeout(250)
                page.wait_for_timeout(extra)

            def shot(name, height=900, full=False, clip_top=0):
                page.set_viewport_size({"width": 1440, "height": height})
                idle(800)
                page.screenshot(path=str(img / f"{name}.png"), full_page=full,
                                clip={"x": 0, "y": clip_top, "width": 1440, "height": height - clip_top}
                                if clip_top else None)
                print("captured", name)

            def nav(label):
                # "설정"이 "참여자 설정"에 걸리지 않도록 메뉴 이름 전체로 찾는다("검토 (2)"처럼 건수가 붙는 메뉴 포함)
                pattern = re.compile(rf"^{re.escape(label)}( \(\d+\))?$")
                page.locator('[data-testid="stSidebar"]').get_by_text(pattern).first.click()
                idle()

            def open_app():
                page.goto(f"http://localhost:{PORT}")
                page.wait_for_selector('[data-testid="stSidebar"]', timeout=60000)
                idle(1200)

            # 1) 업로드: 추적 시작일 필수
            for _ in range(60):
                try:
                    open_app()
                    break
                except Exception:
                    time.sleep(1)
            nav("업로드")
            shot("01_upload_need_start", 620)

            # 2) 시작일 저장 → 파일 업로드
            svc = PrayerService(db)
            svc.save_settings(svc.get_settings().model_copy(update={"tracking_start_date": date(2026, 10, 12)}))
            open_app()
            nav("업로드")
            page.locator('input[type="file"]').set_input_files(str(chat))
            idle(1500)
            page.get_by_role("button", name="가져오기").click()
            idle(2000)
            shot("02_upload_done", 870)

            # 3) 참여자 설정(대상자 지정 전/후)
            nav("참여자 설정")
            svc = PrayerService(db)
            ids = {m["display_name"]: m["id"] for m in svc.members()}
            svc.set_targets({ids[n] for n in TARGETS})
            open_app()
            nav("참여자 설정")
            shot("03_members", 900)

            # 4) 대시보드: 달력 + 요약 + 타임라인
            nav("대시보드")
            page.get_by_role("button", name="24", exact=False).filter(has_text="24 ·").first.click()
            idle(1500)
            shot("04_dashboard", 1900, full=False)

            # 5) 검토: 목록 → START 지정 → 처리 완료 카드
            nav("검토")
            shot("05_review", 1250)
            row = page.locator('[data-testid="stHorizontalBlock"]').filter(has_text="무튼 기도합니다").last
            row.get_by_role("button", name="START", exact=True).click()
            page.wait_for_timeout(1200)
            shot("06_review_done", 1100)

            # 6) 개인별 현황
            nav("개인별 현황")
            page.get_by_role("button", name="임태오", exact=True).click()
            idle(1200)
            shot("07_person", 1700)

            # 7) 수동 기록: 개인별 현황의 날짜에서 바로 추가
            page.get_by_role("button", name="20 · 미완료").first.click()
            idle(1000)
            page.get_by_role("button", name="수동 기록 추가").click()
            idle(1500)
            page.get_by_label("메모 (선택)").fill("전화로 확인 — 종료 인증 누락")
            page.keyboard.press("Enter")
            idle(800)
            page.get_by_role("button", name="추가", exact=True).click()
            page.wait_for_timeout(1200)
            shot("08_manual", 1050)

            # 8) 내보내기(PDF 미리보기)
            nav("내보내기")
            shot("09_export", 1900)

            # 9) 설정
            nav("설정")
            shot("10_settings", 1250)
            browser.close()
    finally:
        server.terminate()

    # PDF 보고서 한 장(설명서 예시)
    from prayer_tracker.reports.pdf import day_png
    (img / "11_pdf_page.png").write_bytes(day_png(PrayerService(db), date(2026, 10, 24)))
    print("done")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
