"""GitHub Release용 파일 준비: 사용자 앱의 [업데이트]가 내려받을 zip과 릴리스 설명을 만든다.

사용: python scripts/publish.py
  1. 최신 배포 zip(dist/기도인증현황_v<버전>.zip)이 지금 소스와 일치하는지 확인(아니면 release.py 먼저)
  2. 사용자 앱과 똑같은 방식으로 zip을 검사(필수 파일, 버전, 개인 데이터가 섞이지 않았는지)
  3. dist/praycheck_v<버전>.zip(영문 이름 사본)과 dist/release_notes_v<버전>.md(SHA256 포함)를 만든다
  4. 태그·push·Release 등록 방법을 출력한다(push와 Release 등록은 관리자가 직접)
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_dist import NAME  # noqa: E402
from release import DIST, STATE, digest, fingerprint  # noqa: E402

from prayer_tracker import updater  # noqa: E402

FORBIDDEN_SUFFIX = (".db", ".db-journal", ".sqlite", ".sqlite3")
FORBIDDEN_PARTS = {"private", "goldset", ".venv", "runtime", ".git"}


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip()


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    src = DIST / f"{NAME}_v{version}.zip"
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    if not src.exists() or state.get("version") != version or state.get("digest") != digest(fingerprint()):
        print(f"배포 zip이 지금 소스와 맞지 않습니다. 먼저 scripts\\release.bat을 실행하세요. (VERSION {version})")
        return 1

    with zipfile.ZipFile(src) as z:
        bad = [n for n in z.namelist()
               if n.lower().endswith(FORBIDDEN_SUFFIX) or FORBIDDEN_PARTS & set(Path(n).parts)]
    if bad:
        print("배포 zip에 들어가면 안 되는 파일이 있습니다:\n  " + "\n  ".join(bad))
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        try:
            files = updater.extract_package(src, Path(tmp) / "staging", version)
        except updater.UpdateError as e:
            print(f"배포 zip 검사 실패: {e}")
            return 1

    out = DIST / f"{updater.ASSET_PREFIX}{version}.zip"
    shutil.copy2(src, out)
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    notes = DIST / f"release_notes_v{version}.md"
    if not notes.exists():
        notes.write_text("## 바뀐 점\n- (사용자가 알아야 할 변경 사항을 쉬운 말로 적어 주세요)\n\n"
                         f"SHA256: {sha}\n", encoding="utf-8")
    else:   # 설명은 그대로 두고 해시 줄만 최신으로
        lines = [l for l in notes.read_text(encoding="utf-8").splitlines() if not l.upper().startswith("SHA256")]
        notes.write_text("\n".join(lines).rstrip() + f"\n\nSHA256: {sha}\n", encoding="utf-8")

    tag = f"v{version}"
    dirty = git("status", "--porcelain", "--untracked-files=no")
    tagged = bool(git("tag", "--list", tag))
    print(f"Release 파일 준비 완료 — v{version} (파일 {len(files)}개 검사 통과)")
    print(f"  올릴 파일 : {out}")
    print(f"  릴리스 설명: {notes}")
    print(f"  SHA256    : {sha}")
    if dirty:
        print("\n[주의] 커밋하지 않은 변경이 있습니다. 커밋한 뒤 태그를 붙이세요.")
    print("\n다음 순서로 공개하세요:")
    step = 1
    if not tagged:
        print(f"  {step}. git tag {tag}")
        step += 1
    print(f"  {step}. git push origin main && git push origin {tag}")
    print(f"  {step + 1}. https://github.com/{updater.REPO}/releases/new?tag={tag} 에서")
    print(f"     제목 '{tag}', 설명은 위 릴리스 설명 파일 내용, 파일은 {out.name} 첨부 → Publish release")
    print("     (Pre-release로 두면 사용자 앱이 보지 못합니다. 'Set as the latest release'를 켜 두세요)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
