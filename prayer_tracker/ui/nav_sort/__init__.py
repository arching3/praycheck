"""사이드바 메뉴 컴포넌트(누르면 이동, 누른 채 끌면 순서 바꾸기)와 순서 계산.

외부 패키지 없이 같은 폴더의 index.html(Streamlit 컴포넌트 v1 규약)을 쓴다.
"""
from __future__ import annotations

from pathlib import Path

_component = None


def merge_order(default: list[str], saved: list[str] | None) -> list[str]:
    """저장된 순서를 적용한다. 없어진 메뉴는 버리고, 새로 생긴 메뉴(업데이트로 추가)는 기본 순서 위치 근처에 끼운다."""
    if not saved:
        return list(default)
    known = set(default)
    out = [k for i, k in enumerate(saved) if k in known and k not in saved[:i]]
    for i, k in enumerate(default):
        if k in out:
            continue
        # 기본 순서에서 바로 앞에 있던 메뉴 뒤에 넣는다(없으면 맨 앞)
        prev = next((p for p in reversed(default[:i]) if p in out), None)
        out.insert(out.index(prev) + 1 if prev else 0, k)
    return out


def interpret(value, order: list[str], last_n) -> tuple[str | None, list[str] | None]:
    """컴포넌트가 돌려준 값을 해석한다. 반환: (이동할 메뉴 key, 저장할 새 순서). 이미 처리한 값(last_n)은 무시.
    컴포넌트 값은 다시 그릴 때마다 같은 값이 돌아오므로 순번 n으로 새 동작만 골라낸다."""
    if not isinstance(value, dict) or value.get("n") is None or value.get("n") == last_n:
        return None, None
    if value.get("action") == "nav" and value.get("key") in order:
        return value["key"], None
    new = value.get("order")
    if value.get("action") == "order" and isinstance(new, list) and sorted(map(str, new)) == sorted(order):
        return None, [str(x) for x in new]
    return None, None


def nav_menu_component(items: list[tuple[str, str]], current: str, key: str):
    """items: [(key, label)]. 돌려준 값은 interpret()으로 해석한다."""
    global _component
    if _component is None:
        import streamlit.components.v1 as components
        _component = components.declare_component("pc_nav_sort", path=str(Path(__file__).parent))
    return _component(items=[{"key": k, "label": lb} for k, lb in items], current=current, key=key, default=None)
