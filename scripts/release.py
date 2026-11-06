"""소스 변경 → 테스트 → 버전 올리기 → 배포 zip. 바뀐 것이 없으면 아무것도 하지 않는다.

사용:
  python scripts/release.py           수동 실행(scripts/release.bat)
  python scripts/release.py --force   변경이 없어도 다시 빌드
  python scripts/release.py --hook    Claude Code Stop 훅용(결과를 JSON systemMessage로, 실패 시 exit 2)

배포 대상 파일의 지문을 dist/.build_state.json에 저장해 두고, 지문이 달라졌을 때만 빌드한다.
VERSION의 패치 번호를 자동으로 올린다(1.0.0 → 1.0.1). 큰 변경은 VERSION을 직접 고치면 그 값을 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_dist import NAME, build  # noqa: E402

DIST = ROOT / "dist"
STATE = DIST / ".build_state.json"
LOG = DIST / "빌드기록.txt"
VERSION = ROOT / "VERSION"
KEEP = 5   # 최근 zip 몇 개를 남길지

# 배포 zip에 들어가는 파일(VERSION은 빌드 때마다 바뀌므로 지문에서 뺀다)
SHIPPED_FILES = ["run.bat", "requirements-runtime.txt", "tools/launcher.ps1", "tools/apply_update.py",
                 "docs/사용방법.pdf", "docs/처음 읽어 주세요.txt"]


def fingerprint() -> dict[str, str]:
    files = [ROOT / f for f in SHIPPED_FILES]
    files += [p for p in (ROOT / "prayer_tracker").rglob("*.py") if "__pycache__" not in p.parts]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files) if p.exists()}


def digest(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def run_tests() -> tuple[bool, str]:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0, out


def bump(version: str) -> str:
    major, minor, patch = (version.split(".") + ["0", "0"])[:3]
    return f"{major}.{minor}.{int(patch) + 1}"


def prune_old_zips() -> None:
    zips = sorted(DIST.glob(f"{NAME}_v*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in zips[KEEP:]:
        old.unlink()


def release(force: bool = False) -> dict:
    files = fingerprint()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    current = VERSION.read_text(encoding="utf-8").strip()
    built = DIST / f"{NAME}_v{state.get('version')}.zip"
    if not force and state.get("digest") == digest(files) and built.exists():
        return {"status": "unchanged", "version": state["version"]}

    ok, out = run_tests()
    tail = "\n".join(out.splitlines()[-40:])
    if not ok:
        return {"status": "test_failed", "output": tail}
    passed = out.splitlines()[-1] if out else ""

    # 지난 빌드와 같은 번호면 패치를 올린다(관리자가 VERSION을 직접 올렸으면 그대로 쓴다)
    version = bump(current) if state.get("version") == current else current
    VERSION.write_text(version + "\n", encoding="utf-8")
    out_zip = build(version)
    prune_old_zips()

    prev = state.get("files", {})
    changed = sorted(f for f in set(files) | set(prev) if files.get(f) != prev.get(f))
    DIST.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({"version": version, "digest": digest(files), "files": files,
                                 "built_at": datetime.now().isoformat(timespec="seconds")},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M}  v{version}  {passed}  변경: {', '.join(changed) or '-'}\n")
    return {"status": "built", "version": version, "zip": str(out_zip), "tests": passed, "changed": changed}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):   # 훅 출력은 UTF-8(Windows 기본 cp949로는 이모지 불가)
        stream.reconfigure(encoding="utf-8")
    hook = "--hook" in sys.argv
    if hook:
        # Stop 훅 입력: 이미 한 번 막았는데도 실패하면 무한 반복을 피하려고 경고만 남긴다
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            payload = {}
    res = release(force="--force" in sys.argv)
    status = res["status"]

    if not hook:
        if status == "unchanged":
            print(f"변경 없음 — 현재 배포본 v{res['version']}")
        elif status == "built":
            print(f"배포 zip 완성: {res['zip']}\n테스트: {res['tests']}\n변경 파일: {', '.join(res['changed']) or '-'}")
        else:
            print("테스트 실패 — 배포 zip을 만들지 않았습니다.\n\n" + res["output"])
            return 1
        return 0

    if status == "unchanged":
        return 0
    if status == "built":
        n = len(res["changed"])
        print(json.dumps({"systemMessage": f"📦 배포 zip 자동 갱신: {NAME}_v{res['version']}.zip "
                                           f"({res['tests']}, 변경 파일 {n}개)"}, ensure_ascii=False))
        return 0
    if payload.get("stop_hook_active"):
        print(json.dumps({"systemMessage": "⚠ 테스트가 계속 실패해 배포 zip을 갱신하지 않았습니다. "
                                           "scripts\\release.bat으로 확인해 주세요."}, ensure_ascii=False))
        return 0
    sys.stderr.write("[자동 배포] 테스트가 실패해 배포 zip을 만들지 않았습니다. 실패를 고쳐 주세요.\n\n"
                     + res["output"] + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
