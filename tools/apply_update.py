"""준비된 업데이트 적용기. tools/launcher.ps1이 앱 서버를 띄우기 전에 실행한다.

사용: python tools/apply_update.py <프로그램 폴더>
  update/ready.json이 없으면 아무것도 하지 않는다(exit 0).

순서(중간에 실패하면 원래 파일로 되돌린다):
  1. 기록 DB(data/prayer_tracker.db)를 data/backup/에 복사(SQLite 백업 기능, 실패하면 적용 중단)
  2. 바뀔 프로그램 파일을 update/backup/v<이전 버전>/에 복사
  3. 새 파일 복사, 새 버전에 없는 prayer_tracker/ 안의 옛 파일 삭제, VERSION은 맨 마지막에 교체
  4. 결과를 update/last_result.json에 남기고 준비물(staging, ready.json)을 지운다

절대 건드리지 않는 것: data/ (DB 백업 사본을 추가할 뿐), runtime/, run.bat(실행 중인 배치 파일은 바꾸면 위험)
표준 라이브러리만 쓴다(프로그램 패키지를 import하지 않음 — 교체 대상이므로).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_NAME = "prayer_tracker.db"
KEEP_DB_BACKUPS = 10
NEVER_TOUCH_TOP = {"data", "runtime", "update", ".git", ".venv"}
NEVER_TOUCH_FILES = {"run.bat"}
OWNED_DIRS = ("prayer_tracker",)   # 이 폴더 안에서 새 버전에 없는 .py는 지운다


def say(msg: str) -> None:
    print(msg, flush=True)


def read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_result(upd: Path, ok: bool, version: str, from_version: str, message: str) -> None:
    (upd / "last_result.json").write_text(json.dumps(
        {"ok": ok, "version": version, "from_version": from_version, "message": message,
         "at": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False, indent=1), encoding="utf-8")


def backup_db(root: Path, new_version: str) -> Path | None:
    db = root / "data" / DB_NAME
    if not db.exists():
        return None
    dest_dir = root / "data" / "backup"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"prayer_tracker_업데이트전_v{new_version}_{datetime.now():%Y%m%d_%H%M%S}.db"
    src = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    chk = sqlite3.connect(str(dest))
    try:
        if chk.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("기록 백업 사본 검사에 실패했습니다.")
    finally:
        chk.close()
    # 업데이트 때 자동으로 만든 백업만 오래된 것부터 정리한다(사용자가 둔 파일은 건드리지 않음)
    olds = sorted(dest_dir.glob("prayer_tracker_업데이트전_v*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in olds[KEEP_DB_BACKUPS:]:
        old.unlink()
    return dest


def plan(root: Path, staging: Path) -> tuple[list[str], list[str]]:
    """(복사할 파일, 지울 옛 파일) — 프로그램 폴더 기준 상대 경로(posix)."""
    new = []
    for p in sorted(staging.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(staging)
        if rel.parts[0] in NEVER_TOUCH_TOP or rel.as_posix() in NEVER_TOUCH_FILES:
            continue
        new.append(rel.as_posix())
    new_set = set(new)
    remove = []
    for d in OWNED_DIRS:
        for p in sorted((root / d).rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            if "__pycache__" not in p.parts and rel not in new_set:
                remove.append(rel)
    return new, remove


def backup_program(root: Path, upd: Path, from_version: str, targets: list[str]) -> tuple[Path, set[str]]:
    """바뀔 파일의 원본을 update/backup/v<이전 버전>/에 복사한다. (백업 폴더, 원래 있던 파일 목록)

    지난번 적용이 중간에 멈춰 백업이 이미 있으면 그 백업이 원본이다(덮어쓰지 않음).
    그때 계획에 없던 파일은 아직 손대지 않은 원본이므로 추가로 백업한다.
    """
    bdir = upd / "backup" / f"v{from_version}"
    manifest = bdir / "_manifest.json"
    if bdir.exists() and manifest.exists():
        m = json.loads(manifest.read_text(encoding="utf-8"))
        planned, existed = set(m["planned"]), set(m["existed"])
    else:
        shutil.rmtree(bdir, ignore_errors=True)
        planned, existed = set(), set()
    for rel in targets:
        if rel in planned:
            continue
        planned.add(rel)
        src = root / rel
        if src.is_file():
            (bdir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, bdir / rel)
            existed.add(rel)
    bdir.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"planned": sorted(planned), "existed": sorted(existed)},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return bdir, existed


def apply(root: Path) -> int:
    upd = root / "update"
    ready = read_json(upd / "ready.json")
    if ready is None:
        return 0
    staging = upd / "staging"
    new_version = str(ready.get("version", ""))
    cur_file = root / "VERSION"
    from_version = cur_file.read_text(encoding="utf-8").strip() if cur_file.exists() else "?"

    def fail(msg: str) -> int:
        # 같은 실패를 매번 반복하지 않도록 준비 표시를 내린다(앱에서 다시 시도할 수 있음)
        (upd / "ready.json").unlink(missing_ok=True)
        write_result(upd, False, new_version, from_version, msg)
        say(f"[업데이트 실패] {msg}")
        say("이전 버전으로 계속 실행합니다. 기록은 그대로입니다.")
        return 1

    staged_version = (staging / "VERSION").read_text(encoding="utf-8").strip() if (staging / "VERSION").exists() else ""
    if not new_version or staged_version != new_version:
        return fail("준비된 업데이트 파일이 온전하지 않습니다. 앱에서 업데이트를 다시 받아 주세요.")
    if from_version == new_version:
        (upd / "ready.json").unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
        return 0

    say(f"새 버전을 적용합니다: v{from_version} → v{new_version}")
    try:
        b = backup_db(root, new_version)
        if b:
            say(f"  기록 백업: data\\backup\\{b.name}")
    except Exception as e:  # noqa: BLE001
        return fail(f"기록을 백업하지 못해 업데이트를 중단했습니다. ({e})")

    new, remove = plan(root, staging)
    # VERSION은 맨 마지막: 중간에 꺼져도 다음 실행 때 '아직 이전 버전'으로 보고 다시 적용한다
    new.sort(key=lambda r: r == "VERSION")
    try:
        bdir, existed = backup_program(root, upd, from_version, new + remove)
    except Exception as e:  # noqa: BLE001
        return fail(f"프로그램 파일을 백업하지 못해 업데이트를 중단했습니다. ({e})")

    try:
        for rel in new:
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staging / rel, dst)
        for rel in remove:
            (root / rel).unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001
        for rel in new + remove:   # 되돌리기
            try:
                if rel in existed:
                    (root / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(bdir / rel, root / rel)
                else:
                    (root / rel).unlink(missing_ok=True)
            except OSError:
                pass
        return fail(f"파일을 바꾸는 중 문제가 생겨 원래대로 되돌렸습니다. ({e})")

    for d in OWNED_DIRS:
        for cache in (root / d).rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
    # 프로그램 백업은 직전 버전 하나만 남긴다
    for old in (upd / "backup").iterdir():
        if old.is_dir() and old.name != bdir.name:
            shutil.rmtree(old, ignore_errors=True)
    (upd / "ready.json").unlink(missing_ok=True)
    shutil.rmtree(staging, ignore_errors=True)
    write_result(upd, True, new_version, from_version, f"v{new_version} 적용 완료")
    say(f"업데이트 완료: v{new_version}")
    return 0


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]).resolve()
    if (root / ".git").exists():
        say("개발 폴더에는 업데이트를 적용하지 않습니다.")
        return 0
    try:
        return apply(root)
    except Exception as e:  # noqa: BLE001 — 예상 못 한 오류도 앱 실행은 막지 않는다
        say(f"[업데이트 실패] 예상하지 못한 오류: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
