"""사이드바 메뉴 순서 바꾸기: 순서 계산과 저장."""
from pathlib import Path

import pytest

from prayer_tracker.service import PrayerService
from prayer_tracker.ui.nav_sort import merge_order

D = ["dashboard", "person", "review", "settings", "update"]


def test_no_saved_order_uses_default():
    assert merge_order(D, []) == D
    assert merge_order(D, None) == D


def test_saved_order_applied():
    s = ["update", "review", "dashboard", "person", "settings"]
    assert merge_order(D, s) == s


def test_removed_and_duplicate_keys_dropped():
    assert merge_order(D, ["review", "gone", "review", "dashboard", "person", "settings", "update"]) == \
        ["review", "dashboard", "person", "settings", "update"]


def test_new_menu_inserted_after_its_default_neighbor():
    # 업데이트로 'settings'가 새로 생김 → 기본 순서에서 바로 앞인 'review' 뒤에
    saved = ["update", "review", "dashboard", "person"]
    assert merge_order(D, saved) == ["update", "review", "settings", "dashboard", "person"]
    # 새 메뉴가 기본 순서 맨 앞이면 맨 앞에
    assert merge_order(D, ["person", "review", "settings", "update"])[0] == "dashboard"


def test_service_roundtrip(tmp_path: Path):
    svc = PrayerService(tmp_path / "t.db")
    assert svc.get_nav_order() == []
    svc.save_nav_order(["update", "dashboard"])
    assert PrayerService(tmp_path / "t.db").get_nav_order() == ["update", "dashboard"]
    svc.save_nav_order([])
    assert svc.get_nav_order() == []


def test_service_ignores_broken_value(tmp_path: Path):
    svc = PrayerService(tmp_path / "t.db")
    svc.conn.execute("INSERT OR REPLACE INTO setting(key,value) VALUES('nav_order','{깨짐')")
    svc.conn.commit()
    assert svc.get_nav_order() == []


# ---- 컴포넌트 값 해석(누르면 이동 / 끌면 순서 저장) ----
from prayer_tracker.ui.nav_sort import interpret  # noqa: E402


def test_interpret_nav_click():
    assert interpret({"action": "nav", "key": "review", "n": 5}, D, None) == ("review", None)


def test_interpret_ignores_already_handled_value():
    # 다시 그릴 때마다 같은 값이 돌아오므로, 처리한 순번이면 무시
    assert interpret({"action": "nav", "key": "review", "n": 5}, D, 5) == (None, None)


def test_interpret_order():
    new = ["update", "dashboard", "person", "review", "settings"]
    assert interpret({"action": "order", "order": new, "n": 6}, D, 5) == (None, new)


@pytest.mark.parametrize("value", [
    None, "x", {}, {"action": "nav", "key": "gone", "n": 1},
    {"action": "order", "order": ["dashboard"], "n": 1},            # 일부만
    {"action": "order", "order": D + ["x"], "n": 1},                # 모르는 메뉴
    {"action": "nav", "key": "review"},                             # 순번 없음
])
def test_interpret_rejects_bad_values(value):
    assert interpret(value, D, None) == (None, None)
