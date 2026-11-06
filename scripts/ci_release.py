"""GitHub Actions(.github/workflows/release.yml)에서 실행: 태그 → 배포 zip과 Release 설명 만들기.

사용: python scripts/ci_release.py <태그>   (예: v1.0.1)
결과(dist/):
  praycheck_v<버전>.zip   Release에 첨부할 파일(사용자 앱이 내려받는 것)
  release_body.md         Release 설명(release_notes/v<버전>.md + SHA256 줄)
GITHUB_OUTPUT이 있으면 version, asset, body 경로를 넘긴다.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_dist import build  # noqa: E402
from package_check import check_notes, check_package  # noqa: E402

from prayer_tracker import updater  # noqa: E402


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    tag = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_REF_NAME", "")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if tag != f"v{version}":
        print(f"::error::태그({tag})와 VERSION 파일(v{version})이 다릅니다.")
        return 1
    try:
        notes = check_notes(version)
        src = build(version)
        files = check_package(src, version)
    except (ValueError, FileNotFoundError) as e:
        print(f"::error::{e}")
        return 1
    asset = ROOT / "dist" / f"{updater.ASSET_PREFIX}{version}.zip"
    shutil.move(str(src), asset)
    sha = hashlib.sha256(asset.read_bytes()).hexdigest()
    body = ROOT / "dist" / "release_body.md"
    body.write_text(notes.rstrip() + f"\n\nSHA256: {sha}\n", encoding="utf-8")
    print(f"v{version}: {asset.name} ({asset.stat().st_size:,} bytes, 파일 {len(files)}개) SHA256 {sha}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"version={version}\nasset={asset.as_posix()}\nbody={body.as_posix()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
