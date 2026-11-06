"""배포용 압축 파일 만들기: 일반 사용자에게 필요한 파일만 담는다.

사용: python scripts/build_dist.py [버전]   →  dist/기도인증현황_v<버전>.zip
담지 않는 것: 개인 데이터(data/, 카카오톡 원본), 개발 환경(.venv, runtime/), 테스트, 평가 정답셋, 문서 원본
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "기도인증현황"

INCLUDE = [
    "run.bat",
    "VERSION",
    "requirements-runtime.txt",
    "tools/launcher.ps1",
    "tools/apply_update.py",
]
# 저장소 위치 → 배포 폴더 위치(사용자가 바로 보도록 맨 위에 둔다)
RENAME = {
    "docs/사용방법.pdf": "사용방법.pdf",
    "docs/처음 읽어 주세요.txt": "처음 읽어 주세요.txt",
}


def build(version: str) -> Path:
    dist = ROOT / "dist"
    stage = dist / NAME
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for rel in INCLUDE:
        src = ROOT / rel
        if not src.exists():
            raise FileNotFoundError(f"배포에 필요한 파일이 없습니다: {rel}")
        (stage / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, stage / rel)
    for src, dst in RENAME.items():
        shutil.copy2(ROOT / src, stage / dst)
    shutil.copytree(ROOT / "prayer_tracker", stage / "prayer_tracker",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (stage / "data").mkdir()   # 기록이 저장될 폴더(빈 채로 배포)
    (stage / "data" / "여기에 기록이 저장됩니다.txt").write_text(
        "이 폴더의 prayer_tracker.db 파일에 모든 기록이 저장됩니다. 백업하려면 이 폴더를 통째로 복사하세요.\n",
        encoding="utf-8")

    out = dist / f"{NAME}_v{version}.zip"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(stage.rglob("*")):
            z.write(f, Path(NAME) / f.relative_to(stage))   # 파일 이름은 UTF-8로 기록(Windows 탐색기 호환)
    shutil.rmtree(stage)   # 압축 직전 작업 폴더는 남기지 않는다
    return out


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else "1.0"))
