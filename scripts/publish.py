"""새 버전 공개 준비(로컬): 검사 후 버전 태그를 붙인다. Release 등록은 GitHub Actions가 한다.

사용: python scripts/publish.py
  1. 최신 배포 zip(dist/기도인증현황_v<버전>.zip)이 지금 소스와 일치하는지(아니면 release.py 먼저)
  2. 그 zip을 사용자 앱과 같은 방식으로 검사(필수 파일, 버전, 개인 데이터 미포함)
  3. 릴리스 설명 release_notes/v<버전>.md가 채워져 커밋되었는지(없으면 틀을 만들고 멈춤)
  4. 커밋하지 않은 변경이 없는지
  5. 주석 태그 v<버전>을 현재 커밋에 붙이고, 관리자가 할 push 명령을 출력한다
태그가 push되면 .github/workflows/release.yml이 테스트 → zip 빌드·검사 → Release 등록을 한다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_dist import NAME  # noqa: E402
from package_check import PLACEHOLDER, check_notes, check_package, notes_path  # noqa: E402
from release import DIST, STATE, digest, fingerprint  # noqa: E402

from prayer_tracker import updater  # noqa: E402


def git(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (r.stdout + r.stderr).strip()


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    tag = f"v{version}"

    src = DIST / f"{NAME}_v{version}.zip"
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    if not src.exists() or state.get("version") != version or state.get("digest") != digest(fingerprint()):
        print(f"배포 zip이 지금 소스와 맞지 않습니다. 먼저 scripts\\release.bat을 실행하세요. (VERSION {version})")
        return 1
    try:
        files = check_package(src, version)
    except ValueError as e:
        print(e)
        return 1

    notes = notes_path(version)
    if not notes.exists():
        notes.parent.mkdir(exist_ok=True)
        notes.write_text(f"## 바뀐 점\n- {PLACEHOLDER}을 쉬운 말로 적어 주세요)\n", encoding="utf-8")
        print(f"릴리스 설명 틀을 만들었습니다: {notes.relative_to(ROOT)}\n내용을 채워 커밋한 뒤 다시 실행하세요.")
        return 1
    try:
        check_notes(version)
    except ValueError as e:
        print(e)
        return 1

    code, dirty = git("status", "--porcelain", "--untracked-files=no")
    rel = notes.relative_to(ROOT).as_posix()
    code2, tracked = git("ls-files", "--error-unmatch", rel)
    if dirty or code2 != 0:
        print("커밋하지 않은 변경이 있습니다(릴리스 설명 포함). 먼저 커밋하세요.")
        print(dirty or f"?? {rel}")
        return 1

    _, head = git("rev-parse", "HEAD")
    code, tagged = git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
    if code == 0 and tagged != head:
        print(f"태그 {tag}가 이미 다른 커밋({tagged[:7]})에 있습니다. VERSION을 올리거나 태그를 확인하세요.")
        return 1
    if code != 0:
        code, out = git("tag", "-a", tag, "-m", f"기도 인증 현황 {tag}")
        if code != 0:
            print(f"태그를 만들지 못했습니다: {out}")
            return 1
        print(f"태그 {tag}를 만들었습니다 → {head[:7]}")
    else:
        print(f"태그 {tag}가 이미 현재 커밋에 있습니다.")

    print(f"공개 준비 완료 — v{version} (배포 파일 {len(files)}개 검사 통과)")
    print("\n관리자가 실행할 명령(이 push가 곧 사용자 공개입니다):")
    print("  git push --follow-tags")
    print(f"\npush 후 진행 상황: https://github.com/{updater.REPO}/actions")
    print(f"완료되면 Release: https://github.com/{updater.REPO}/releases/tag/{tag}")
    print("공개를 미루려면 'git push'만 하고(태그 제외) 나중에 'git push origin " + tag + "'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
