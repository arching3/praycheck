"""기도 인증 현황. 버전은 프로젝트 루트(배포 폴더)의 VERSION 파일 하나로 관리한다."""
from pathlib import Path

try:
    __version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    __version__ = "dev"
