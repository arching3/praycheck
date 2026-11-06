"""배포 zip 검사(로컬 publish.py와 GitHub Actions ci_release.py가 함께 쓴다).

사용자 앱의 업데이트와 똑같은 방식(updater.extract_package)으로 풀어 보고,
개인 데이터나 개발 파일이 섞이지 않았는지 확인한다.
"""
from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prayer_tracker import updater  # noqa: E402

FORBIDDEN_SUFFIX = (".db", ".db-journal", ".sqlite", ".sqlite3")
FORBIDDEN_PARTS = {"private", "goldset", ".venv", "runtime", ".git", "update", "tests", "eval"}


def check_package(zip_path: Path, version: str) -> list[str]:
    """문제가 있으면 ValueError(한국어 메시지). 통과하면 사용자에게 적용될 파일 목록."""
    with zipfile.ZipFile(zip_path) as z:
        bad = [n for n in z.namelist()
               if n.lower().endswith(FORBIDDEN_SUFFIX) or FORBIDDEN_PARTS & set(Path(n).parts)]
    if bad:
        raise ValueError("배포 zip에 들어가면 안 되는 파일이 있습니다:\n  " + "\n  ".join(bad))
    with tempfile.TemporaryDirectory() as tmp:
        try:
            return updater.extract_package(zip_path, Path(tmp) / "staging", version)
        except updater.UpdateError as e:
            raise ValueError(f"배포 zip 검사 실패: {e}") from e


def notes_path(version: str) -> Path:
    return ROOT / "release_notes" / f"v{version}.md"


PLACEHOLDER = "(사용자가 알아야 할 변경 사항"


def check_notes(version: str) -> str:
    """커밋된 릴리스 설명(사용자가 업데이트 화면에서 읽음). 없거나 비어 있으면 ValueError."""
    p = notes_path(version)
    if not p.exists():
        raise ValueError(f"릴리스 설명이 없습니다: release_notes/v{version}.md")
    text = p.read_text(encoding="utf-8-sig").strip()
    body = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not body or PLACEHOLDER in text:
        raise ValueError(f"릴리스 설명이 비어 있습니다: release_notes/v{version}.md")
    return text
