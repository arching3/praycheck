"""반자동 업데이트: GitHub Release에서 새 버전을 확인하고, 내려받아 '준비'까지만 한다.

실제 교체는 앱이 꺼진 뒤 다음 실행 때 tools/launcher.ps1 → tools/apply_update.py가 한다.
(실행 중인 앱이 자기 파일을 바꾸지 않기 위해서)

준비 결과(프로그램 폴더 안):
  update/staging/      새 버전 파일(배포 zip의 내용, data/ 제외)
  update/ready.json    준비 완료 표시. 이 파일이 있으면 다음 실행 때 적용된다.

사용자 기록(data/)은 여기서 절대 건드리지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

REPO = "arching3/praycheck"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
ASSET_PREFIX = "praycheck_v"          # Release에 올리는 zip 이름(영문: GitHub가 한글 파일명을 바꿔 버림)
USER_AGENT = "praycheck-updater"
NO_CHECK_ENV = "PRAYER_TRACKER_NO_UPDATE_CHECK"   # 테스트·설명서 캡처에서 네트워크 확인을 끈다

# 배포 zip 안에 반드시 있어야 하는 파일(없으면 깨진 파일로 본다)
REQUIRED = ("VERSION", "run.bat", "requirements-runtime.txt", "tools/launcher.ps1",
            "tools/apply_update.py", "prayer_tracker/__init__.py", "prayer_tracker/ui/app.py")
# 업데이트로 절대 들여오지 않는 최상위 폴더
SKIP_TOP = {"data", "runtime", "update"}


class UpdateError(Exception):
    """사용자에게 그대로 보여 줄 한국어 메시지를 담는다."""


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    published_at: str
    asset_name: str
    asset_url: str
    asset_size: int
    sha256: str | None
    page_url: str


# ------------------------------------------------------------------ 버전
def parse_version(text: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    if not m:
        return None
    parts = [int(x) for x in m.group(1).split(".")]
    return tuple(parts + [0] * (3 - len(parts)))


def is_newer(remote: str, local: str) -> bool:
    r, cur = parse_version(remote), parse_version(local)
    if r is None:
        return False
    if cur is None:          # "dev" 등 알 수 없는 현재 버전이면 새 버전으로 보지 않는다
        return False
    return r > cur


# ------------------------------------------------------------------ 확인
def _get(url: str, timeout: float, accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def parse_release(data: dict) -> ReleaseInfo:
    tag = str(data.get("tag_name") or "")
    version = tag.lstrip("vV")
    if parse_version(version) is None:
        raise UpdateError(f"업데이트 정보의 버전 형식을 알 수 없습니다: {tag!r}")
    assets = [a for a in data.get("assets") or [] if str(a.get("name", "")).lower().endswith(".zip")]
    preferred = [a for a in assets if str(a.get("name", "")).startswith(ASSET_PREFIX)]
    asset = (preferred or assets or [None])[0]
    if asset is None:
        raise UpdateError(f"v{version} 업데이트에 내려받을 파일이 없습니다. 관리자에게 알려 주세요.")
    notes = str(data.get("body") or "")
    sha = None
    digest = str(asset.get("digest") or "")
    if digest.startswith("sha256:"):
        sha = digest.split(":", 1)[1].lower()
    else:   # 릴리스 설명에 적어 둔 "SHA256: <해시>"를 대신 쓴다
        m = re.search(r"SHA256\s*[:=]\s*([0-9a-fA-F]{64})", notes)
        sha = m.group(1).lower() if m else None
    return ReleaseInfo(version=version, tag=tag, notes=notes, published_at=str(data.get("published_at") or ""),
                       asset_name=str(asset.get("name")), asset_url=str(asset.get("browser_download_url")),
                       asset_size=int(asset.get("size") or 0), sha256=sha,
                       page_url=str(data.get("html_url") or RELEASES_PAGE))


def fetch_latest(timeout: float = 5.0) -> ReleaseInfo:
    try:
        with _get(API_LATEST, timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("아직 공개된 업데이트가 없습니다.") from e
        if e.code in (403, 429):
            raise UpdateError("업데이트 서버 확인 횟수가 잠시 초과되었습니다. 한 시간쯤 뒤에 다시 시도해 주세요.") from e
        raise UpdateError(f"업데이트 서버에 접속하지 못했습니다. (HTTP {e.code})") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError("업데이트를 확인하지 못했습니다. 인터넷 연결을 확인해 주세요.") from e
    except ValueError as e:
        raise UpdateError("업데이트 정보를 읽지 못했습니다.") from e
    return parse_release(data)


def check_disabled() -> bool:
    return os.environ.get(NO_CHECK_ENV, "") not in ("", "0")


# ------------------------------------------------------------------ 상태
def update_dir(root: Path) -> Path:
    return Path(root) / "update"


def is_dev_checkout(root: Path) -> bool:
    """개발 폴더(git 저장소)에는 업데이트를 적용하지 않는다."""
    return (Path(root) / ".git").exists()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def prepared(root: Path) -> dict | None:
    """준비가 끝나 다음 실행 때 적용될 업데이트 정보(없으면 None)."""
    info = _read_json(update_dir(root) / "ready.json")
    if info and (update_dir(root) / "staging" / "VERSION").exists():
        return info
    return None


def last_result(root: Path) -> dict | None:
    """마지막 적용 결과(update/last_result.json): {"ok": bool, "version", "from_version", "message", "at"}."""
    return _read_json(update_dir(root) / "last_result.json")


# ------------------------------------------------------------------ 준비
def _safe_member(name: str) -> PurePosixPath | None:
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or (p.parts and ":" in p.parts[0]):
        return None
    return p


def _download(url: str, dest: Path, expected_size: int, timeout: float,
              progress: Callable[[int, int], None] | None) -> str:
    h = hashlib.sha256()
    done = 0
    try:
        with _get(url, timeout, accept="application/octet-stream") as r, dest.open("wb") as f:
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, expected_size)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError("업데이트 파일을 내려받지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.") from e
    if expected_size and done != expected_size:
        raise UpdateError("업데이트 파일이 끝까지 받아지지 않았습니다. 다시 시도해 주세요.")
    return h.hexdigest()


def extract_package(zip_path: Path, staging: Path, expect_version: str) -> list[str]:
    """배포 zip을 검사하고 staging에 푼다(최상위 폴더 하나는 벗겨 낸다). 들여온 파일 목록을 돌려준다."""
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise UpdateError("업데이트 파일이 손상되었습니다. 다시 시도해 주세요.") from e
    with z:
        if z.testzip() is not None:
            raise UpdateError("업데이트 파일이 손상되었습니다. 다시 시도해 주세요.")
        members = [(i, _safe_member(i.filename)) for i in z.infolist() if not i.is_dir()]
        if any(p is None for _, p in members):
            raise UpdateError("업데이트 파일에 허용되지 않는 경로가 있습니다. 관리자에게 알려 주세요.")
        tops = {p.parts[0] for _, p in members if len(p.parts) > 1}
        strip = len(tops) == 1 and all(len(p.parts) > 1 for _, p in members)
        files: dict[str, zipfile.ZipInfo] = {}
        for info, p in members:
            rel = PurePosixPath(*p.parts[1:]) if strip else p
            if rel.parts[0] in SKIP_TOP or "__pycache__" in rel.parts or rel.suffix == ".pyc":
                continue
            files[rel.as_posix()] = info
        missing = [f for f in REQUIRED if f not in files]
        if missing:
            raise UpdateError(f"업데이트 파일에 필요한 구성이 빠져 있습니다: {', '.join(missing)}")
        got = z.read(files["VERSION"]).decode("utf-8-sig").strip()
        if got != expect_version:
            raise UpdateError(f"업데이트 파일의 버전({got})이 안내된 버전({expect_version})과 다릅니다.")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        for rel, info in files.items():
            out = staging / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    return sorted(files)


def prepare(root: Path, info: ReleaseInfo, current_version: str, timeout: float = 30.0,
            progress: Callable[[int, int], None] | None = None) -> dict:
    """새 버전을 내려받아 검사하고 update/staging에 풀어 둔다. 실패하면 UpdateError."""
    root = Path(root)
    if is_dev_checkout(root):
        raise UpdateError("개발 폴더에서는 업데이트를 준비하지 않습니다.")
    if not is_newer(info.version, current_version):
        raise UpdateError(f"이미 최신 버전입니다. (현재 v{current_version})")
    upd = update_dir(root)
    upd.mkdir(parents=True, exist_ok=True)
    ready = upd / "ready.json"
    if ready.exists():
        ready.unlink()      # 이전 준비는 무효화하고 새로 준비한다
    part = upd / "download.part"
    try:
        sha = _download(info.asset_url, part, info.asset_size, timeout, progress)
        if info.sha256 and sha != info.sha256:
            raise UpdateError("업데이트 파일의 검증 값이 맞지 않습니다. 다시 시도해 주세요.")
        files = extract_package(part, upd / "staging_new", info.version)
        staging = upd / "staging"
        if staging.exists():
            shutil.rmtree(staging)
        (upd / "staging_new").rename(staging)
    except Exception:
        shutil.rmtree(upd / "staging_new", ignore_errors=True)
        raise
    finally:
        part.unlink(missing_ok=True)
    meta = {"version": info.version, "from_version": current_version, "sha256": sha, "files": files,
            "notes": info.notes, "prepared_at": datetime.now().isoformat(timespec="seconds")}
    ready.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")   # 마지막에 써야 '완료'
    return meta


def cancel(root: Path) -> None:
    """준비해 둔 업데이트를 취소한다(update/ 안의 준비물만 지운다)."""
    upd = update_dir(root)
    (upd / "ready.json").unlink(missing_ok=True)
    shutil.rmtree(upd / "staging", ignore_errors=True)


def info_dict(info: ReleaseInfo) -> dict:
    return asdict(info)
