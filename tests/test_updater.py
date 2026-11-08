"""반자동 업데이트(prayer_tracker/updater.py + tools/apply_update.py) 테스트. 네트워크·실제 data/ 사용 없음."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import sqlite3
import urllib.error
import zipfile
from pathlib import Path

import pytest

from prayer_tracker import updater
from prayer_tracker.updater import UpdateError

PROJECT = Path(__file__).resolve().parent.parent
TOP = "기도인증현황"

_spec = importlib.util.spec_from_file_location("apply_update_under_test", PROJECT / "tools" / "apply_update.py")
au = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(au)


# ---------------------------------------------------------------- helpers
class FakeResp:
    def __init__(self, data: bytes):
        self._b = io.BytesIO(data)

    def read(self, n: int = -1) -> bytes:
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def new_files(version: str = "1.1.0") -> dict[str, bytes]:
    files = {rel: f"new {rel}".encode() for rel in updater.REQUIRED}
    files["VERSION"] = version.encode()
    files["run.bat"] = b"NEW RUN BAT"
    files["prayer_tracker/new_module.py"] = b"# new module\n"
    return files


def build_zip(path: Path, files: dict[str, bytes], top: str | None = TOP, extra: dict[str, bytes] | None = None) -> bytes:
    allf = dict(files)
    allf["data/여기에.txt"] = "package readme".encode()
    allf["data/prayer_tracker.db"] = b"JUNK-NOT-A-DB"
    allf.update(extra or {})
    with zipfile.ZipFile(path, "w") as z:
        for rel, b in allf.items():
            z.writestr(f"{top}/{rel}" if top else rel, b)
    return path.read_bytes()


def release_for(data: bytes, version: str = "1.1.0", sha_value: str | None = "auto", size: int | None = None):
    return updater.ReleaseInfo(
        version=version, tag=f"v{version}", notes="n", published_at="", asset_name="praycheck_v.zip",
        asset_url="https://example.invalid/x.zip", asset_size=len(data) if size is None else size,
        sha256=sha(data) if sha_value == "auto" else sha_value, page_url="https://example.invalid")


def mock_download(monkeypatch, data: bytes):
    monkeypatch.setattr(updater, "_get", lambda url, timeout, accept="": FakeResp(data))


def make_app(tmp_path: Path) -> Path:
    app = tmp_path / "app"
    (app / "prayer_tracker" / "ui").mkdir(parents=True)
    (app / "tools").mkdir()
    (app / "data").mkdir()
    (app / "VERSION").write_text("1.0.0", encoding="utf-8")
    (app / "run.bat").write_bytes(b"OLD RUN BAT")
    (app / "requirements-runtime.txt").write_bytes(b"old req")
    (app / "prayer_tracker" / "__init__.py").write_bytes(b"# old init")
    (app / "prayer_tracker" / "old_module.py").write_bytes(b"# stale")
    (app / "prayer_tracker" / "ui" / "app.py").write_bytes(b"# old app")
    (app / "tools" / "launcher.ps1").write_bytes(b"old launcher")
    (app / "tools" / "apply_update.py").write_bytes(b"# old apply")
    con = sqlite3.connect(app / "data" / "prayer_tracker.db")
    con.execute("create table t(id integer primary key, v text)")
    con.executemany("insert into t(v) values (?)", [("가",), ("나",), ("다",)])
    con.commit()
    con.close()
    (app / "data" / "memo.txt").write_bytes(b"user memo")
    return app


def snapshot(app: Path) -> dict[str, bytes]:
    return {p.relative_to(app).as_posix(): p.read_bytes()
            for p in sorted(app.rglob("*")) if p.is_file() and p.relative_to(app).parts[0] != "update"}


def db_rows(p: Path):
    con = sqlite3.connect(p)
    try:
        return con.execute("select id, v from t order by id").fetchall()
    finally:
        con.close()


def stage(monkeypatch, tmp_path, app, files=None, version="1.1.0") -> dict:
    z = tmp_path / "pkg.zip"
    data = build_zip(z, files or new_files(version))
    mock_download(monkeypatch, data)
    return updater.prepare(app, release_for(data, version), "1.0.0")


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path)


# ---------------------------------------------------------------- 1. 버전
def test_parse_version():
    assert updater.parse_version("1.2.3") == (1, 2, 3)
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("1.0") == (1, 0, 0)
    assert updater.parse_version("2") == (2, 0, 0)
    assert updater.parse_version("dev") is None
    assert updater.parse_version("") is None
    assert updater.parse_version("1.0-beta") is None


def test_is_newer():
    assert updater.is_newer("v1.0.1", "1.0.0")
    assert not updater.is_newer("1.0", "1.0.0")
    assert not updater.is_newer("1.0.0", "1.0")
    assert updater.is_newer("1.0.10", "1.0.9")
    assert not updater.is_newer("1.0.9", "1.0.10")
    assert not updater.is_newer("2.0.0", "dev")
    assert not updater.is_newer("garbage", "1.0.0")
    assert not updater.is_newer("", "1.0.0")


# ---------------------------------------------------------------- 2. parse_release
H = "ab" * 32


def test_parse_release_prefers_prefix_asset_and_digest():
    r = updater.parse_release({"tag_name": "v1.2.0", "body": "x", "html_url": "u", "assets": [
        {"name": "other.zip", "browser_download_url": "o", "size": 1},
        {"name": "praycheck_v1.2.0.zip", "browser_download_url": "p", "size": 5, "digest": "sha256:" + H.upper()},
        {"name": "notes.txt", "browser_download_url": "t", "size": 1}]})
    assert r.version == "1.2.0" and r.asset_name == "praycheck_v1.2.0.zip"
    assert r.asset_url == "p" and r.asset_size == 5 and r.sha256 == H


def test_parse_release_falls_back_to_any_zip_and_body_sha():
    r = updater.parse_release({"tag_name": "1.2.0", "body": f"hello\nSHA256: {H}\n", "assets": [
        {"name": "other.zip", "browser_download_url": "o", "size": 1}]})
    assert r.asset_name == "other.zip" and r.sha256 == H


def test_parse_release_no_sha():
    r = updater.parse_release({"tag_name": "v1.2.0", "body": "", "assets": [
        {"name": "praycheck_v1.zip", "browser_download_url": "o"}]})
    assert r.sha256 is None and r.asset_size == 0


def test_parse_release_errors():
    with pytest.raises(UpdateError):
        updater.parse_release({"tag_name": "v1.2.0", "assets": [{"name": "a.txt"}]})
    with pytest.raises(UpdateError):
        updater.parse_release({"tag_name": "v1.2.0"})
    with pytest.raises(UpdateError):
        updater.parse_release({"tag_name": "nightly", "assets": [{"name": "a.zip"}]})
    with pytest.raises(UpdateError):
        updater.parse_release({})


# ---------------------------------------------------------------- 3. fetch_latest
def test_fetch_latest_ok(monkeypatch):
    body = json.dumps({"tag_name": "v1.5.0", "assets": [{"name": "praycheck_v1.5.0.zip",
                                                         "browser_download_url": "u", "size": 3}]}).encode()
    monkeypatch.setattr(updater, "_get", lambda *a, **k: FakeResp(body))
    assert updater.fetch_latest().version == "1.5.0"


@pytest.mark.parametrize("exc", [
    urllib.error.HTTPError("u", 404, "nf", {}, None),
    urllib.error.HTTPError("u", 403, "rl", {}, None),
    urllib.error.HTTPError("u", 429, "rl", {}, None),
    urllib.error.HTTPError("u", 500, "boom", {}, None),
    urllib.error.URLError("no net"),
    TimeoutError(),
])
def test_fetch_latest_errors_map_to_update_error(monkeypatch, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(updater, "_get", boom)
    with pytest.raises(UpdateError) as ei:
        updater.fetch_latest()
    assert str(ei.value)


def test_fetch_latest_bad_json(monkeypatch):
    monkeypatch.setattr(updater, "_get", lambda *a, **k: FakeResp(b"<html>"))
    with pytest.raises(UpdateError):
        updater.fetch_latest()


# ---------------------------------------------------------------- 4. prepare
def test_prepare_success(monkeypatch, tmp_path, app):
    meta = stage(monkeypatch, tmp_path, app)
    upd = app / "update"
    assert meta["version"] == "1.1.0" and meta["from_version"] == "1.0.0"
    assert (upd / "ready.json").exists()
    assert (upd / "staging" / "VERSION").read_text() == "1.1.0"
    assert (upd / "staging" / "prayer_tracker" / "new_module.py").exists()
    assert not (upd / "staging" / "data").exists()
    assert not any("data/" in f for f in meta["files"])
    assert not (upd / "staging_new").exists() and not (upd / "download.part").exists()
    assert updater.prepared(app)["version"] == "1.1.0"
    # 프로그램 폴더 본체와 data/는 그대로
    assert (app / "VERSION").read_text() == "1.0.0"
    assert (app / "data" / "prayer_tracker.db").read_bytes() != b"JUNK-NOT-A-DB"


def test_prepare_progress_called(monkeypatch, tmp_path, app):
    z = tmp_path / "p.zip"
    data = build_zip(z, new_files())
    mock_download(monkeypatch, data)
    calls = []
    updater.prepare(app, release_for(data), "1.0.0", progress=lambda d, t: calls.append((d, t)))
    assert calls and calls[-1] == (len(data), len(data))


def _assert_clean_failure(app):
    upd = app / "update"
    assert not (upd / "ready.json").exists()
    assert not (upd / "staging_new").exists()
    assert not (upd / "download.part").exists()
    assert updater.prepared(app) is None


def test_prepare_sha_mismatch(monkeypatch, tmp_path, app):
    data = build_zip(tmp_path / "p.zip", new_files())
    mock_download(monkeypatch, data)
    with pytest.raises(UpdateError):
        updater.prepare(app, release_for(data, sha_value="0" * 64), "1.0.0")
    _assert_clean_failure(app)


def test_prepare_size_mismatch(monkeypatch, tmp_path, app):
    data = build_zip(tmp_path / "p.zip", new_files())
    mock_download(monkeypatch, data)
    with pytest.raises(UpdateError):
        updater.prepare(app, release_for(data, size=len(data) + 10), "1.0.0")
    _assert_clean_failure(app)


def test_prepare_version_in_zip_differs(monkeypatch, tmp_path, app):
    data = build_zip(tmp_path / "p.zip", new_files("1.9.9"))
    mock_download(monkeypatch, data)
    with pytest.raises(UpdateError):
        updater.prepare(app, release_for(data, "1.1.0"), "1.0.0")
    _assert_clean_failure(app)


def test_prepare_missing_required(monkeypatch, tmp_path, app):
    files = new_files()
    del files["tools/apply_update.py"]
    data = build_zip(tmp_path / "p.zip", files)
    mock_download(monkeypatch, data)
    with pytest.raises(UpdateError) as ei:
        updater.prepare(app, release_for(data), "1.0.0")
    assert "apply_update" in str(ei.value)
    _assert_clean_failure(app)


def test_prepare_path_traversal(monkeypatch, tmp_path, app):
    data = build_zip(tmp_path / "p.zip", new_files(), extra={"../evil.py": b"x"})
    mock_download(monkeypatch, data)
    with pytest.raises(UpdateError):
        updater.prepare(app, release_for(data), "1.0.0")
    _assert_clean_failure(app)
    assert not (app / "evil.py").exists() and not (app / "update" / "evil.py").exists()


def test_prepare_corrupt_zip(monkeypatch, tmp_path, app):
    data = b"this is not a zip"
    mock_download(monkeypatch, data)
    with pytest.raises(UpdateError):
        updater.prepare(app, release_for(data), "1.0.0")
    _assert_clean_failure(app)


def test_prepare_download_network_error(monkeypatch, app):
    def boom(*a, **k):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(updater, "_get", boom)
    info = release_for(b"x")
    with pytest.raises(UpdateError):
        updater.prepare(app, info, "1.0.0")
    _assert_clean_failure(app)


def test_prepare_refuses_dev_checkout(monkeypatch, tmp_path, app):
    (app / ".git").mkdir()
    data = build_zip(tmp_path / "p.zip", new_files())
    mock_download(monkeypatch, data)
    with pytest.raises(UpdateError):
        updater.prepare(app, release_for(data), "1.0.0")
    assert not (app / "update" / "staging").exists()


def test_prepare_refuses_not_newer(monkeypatch, tmp_path, app):
    data = build_zip(tmp_path / "p.zip", new_files("1.0.0"))
    mock_download(monkeypatch, data)
    with pytest.raises(UpdateError):
        updater.prepare(app, release_for(data, "1.0.0"), "1.0.0")
    assert updater.prepared(app) is None


def test_failed_prepare_keeps_previous_staging_but_invalidates_ready(monkeypatch, tmp_path, app):
    stage(monkeypatch, tmp_path, app)
    data = build_zip(tmp_path / "p2.zip", new_files("1.2.0"))
    mock_download(monkeypatch, data)
    with pytest.raises(UpdateError):
        updater.prepare(app, release_for(data, "1.2.0", sha_value="0" * 64), "1.0.0")
    assert not (app / "update" / "ready.json").exists()
    assert updater.prepared(app) is None


def test_cancel(monkeypatch, tmp_path, app):
    stage(monkeypatch, tmp_path, app)
    assert updater.prepared(app) is not None
    updater.cancel(app)
    assert updater.prepared(app) is None
    assert not (app / "update" / "staging").exists()
    updater.cancel(app)  # 두 번 불러도 안전


def test_extract_package_without_top_folder(tmp_path):
    z = tmp_path / "flat.zip"
    build_zip(z, new_files(), top=None)
    files = updater.extract_package(z, tmp_path / "st", "1.1.0")
    assert "VERSION" in files and not any(f.startswith("data/") for f in files)


def test_extract_package_skips_pycache(tmp_path):
    z = tmp_path / "pc.zip"
    build_zip(z, new_files(), extra={"prayer_tracker/__pycache__/x.cpython-313.pyc": b"c", "prayer_tracker/y.pyc": b"c"})
    files = updater.extract_package(z, tmp_path / "st", "1.1.0")
    assert not any(f.endswith(".pyc") or "__pycache__" in f for f in files)


# ---------------------------------------------------------------- 5. apply 성공
def test_apply_nothing_staged(app):
    before = snapshot(app)
    assert au.apply(app) == 0
    assert snapshot(app) == before
    assert not (app / "update" / "last_result.json").exists()


def test_apply_full_success(monkeypatch, tmp_path, app):
    before = snapshot(app)
    db_path = app / "data" / "prayer_tracker.db"
    db_sha, rows = sha(db_path.read_bytes()), db_rows(db_path)
    stage(monkeypatch, tmp_path, app)

    assert au.apply(app) == 0

    assert (app / "VERSION").read_text() == "1.1.0"
    assert (app / "prayer_tracker" / "__init__.py").read_bytes() == b"new prayer_tracker/__init__.py"
    assert (app / "prayer_tracker" / "ui" / "app.py").read_bytes() == b"new prayer_tracker/ui/app.py"
    assert (app / "prayer_tracker" / "new_module.py").exists()
    assert (app / "tools" / "launcher.ps1").read_bytes() == b"new tools/launcher.ps1"
    assert not (app / "prayer_tracker" / "old_module.py").exists()
    assert (app / "run.bat").read_bytes() == b"OLD RUN BAT"        # run.bat은 교체하지 않는다
    # data/ 불변
    assert sha(db_path.read_bytes()) == db_sha and db_rows(db_path) == rows
    assert (app / "data" / "memo.txt").read_bytes() == b"user memo"
    assert (app / "data" / "여기에.txt").exists() is False        # 패키지의 data/는 들어오지 않음
    backups = list((app / "data" / "backup").glob("prayer_tracker_업데이트전_v1.1.0_*.db"))
    assert len(backups) == 1 and db_rows(backups[0]) == rows
    # 프로그램 백업
    b = app / "update" / "backup" / "v1.0.0"
    assert (b / "_manifest.json").exists()
    assert (b / "prayer_tracker" / "old_module.py").read_bytes() == b"# stale"
    assert (b / "prayer_tracker" / "__init__.py").read_bytes() == before["prayer_tracker/__init__.py"]
    assert (b / "VERSION").read_text() == "1.0.0"
    assert not (b / "run.bat").exists()
    # 정리와 결과
    assert not (app / "update" / "ready.json").exists() and not (app / "update" / "staging").exists()
    res = updater.last_result(app)
    assert res["ok"] is True and res["version"] == "1.1.0" and res["from_version"] == "1.0.0"
    # 같은 버전 재실행은 아무 일 없음
    assert au.apply(app) == 0


def test_apply_removes_pycache_and_keeps_only_latest_backup(monkeypatch, tmp_path, app):
    (app / "prayer_tracker" / "__pycache__").mkdir()
    (app / "prayer_tracker" / "__pycache__" / "x.pyc").write_bytes(b"c")
    (app / "update" / "backup" / "v0.9.0").mkdir(parents=True)
    stage(monkeypatch, tmp_path, app)
    assert au.apply(app) == 0
    assert not (app / "prayer_tracker" / "__pycache__").exists()
    assert not (app / "update" / "backup" / "v0.9.0").exists()
    assert (app / "update" / "backup" / "v1.0.0").exists()


def test_apply_without_db_still_works(monkeypatch, tmp_path, app):
    (app / "data" / "prayer_tracker.db").unlink()
    stage(monkeypatch, tmp_path, app)
    assert au.apply(app) == 0
    assert (app / "VERSION").read_text() == "1.1.0"


# ---------------------------------------------------------------- 6. 롤백
def test_apply_rollback_on_copy_failure(monkeypatch, tmp_path, app):
    before = snapshot(app)
    db_path = app / "data" / "prayer_tracker.db"
    rows = db_rows(db_path)
    stage(monkeypatch, tmp_path, app)

    real = shutil.copy2
    state = {"n": 0}

    def flaky(src, dst, *a, **k):
        # 복사 단계(staging -> app)에서만, 몇 개 복사한 뒤 특정 파일에서 실패
        if "staging" in Path(src).parts:
            state["n"] += 1
            if Path(dst).name == "launcher.ps1":
                raise OSError("disk error")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(au.shutil, "copy2", flaky)
    assert au.apply(app) == 1
    monkeypatch.setattr(au.shutil, "copy2", real)

    assert state["n"] >= 2
    after = snapshot(app)
    after_program = {k: v for k, v in after.items() if not k.startswith("data/backup/")}
    assert after_program == before                               # 낡은 모듈 포함 전부 원상 복구
    assert not (app / "prayer_tracker" / "new_module.py").exists()
    assert (app / "VERSION").read_text() == "1.0.0"
    assert not (app / "update" / "ready.json").exists()
    res = updater.last_result(app)
    assert res["ok"] is False and res["message"]
    assert db_rows(db_path) == rows


def test_apply_rollback_when_removal_fails(monkeypatch, tmp_path, app):
    """삭제 단계에서 실패해도 이미 복사된 새 파일은 되돌려진다."""
    before = snapshot(app)
    stage(monkeypatch, tmp_path, app)
    orig_unlink = Path.unlink

    def bad_unlink(self, *a, **k):
        if self.name == "old_module.py" and (app / "update") not in self.parents:
            raise PermissionError("locked")
        return orig_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", bad_unlink)
    rc = au.apply(app)
    monkeypatch.setattr(Path, "unlink", orig_unlink)
    assert rc == 1
    after = {k: v for k, v in snapshot(app).items() if not k.startswith("data/backup/")}
    assert after == before


# ---------------------------------------------------------------- 7. DB 백업 실패
def test_apply_db_backup_failure_changes_nothing(monkeypatch, tmp_path, app):
    stage(monkeypatch, tmp_path, app)
    before = snapshot(app)

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(au, "backup_db", boom)
    assert au.apply(app) == 1
    assert snapshot(app) == before
    assert not (app / "update" / "ready.json").exists()
    assert updater.last_result(app)["ok"] is False


def test_backup_db_prunes_only_auto_backups(app):
    d = app / "data" / "backup"
    d.mkdir()
    user = d / "내가_만든_백업.db"
    user.write_bytes(b"mine")
    import os
    for i in range(au.KEEP_DB_BACKUPS + 3):
        p = d / f"prayer_tracker_업데이트전_v0.0.{i}_20200101_000000.db"
        p.write_bytes(b"x")
        os.utime(p, (1_000_000 + i, 1_000_000 + i))
    au.backup_db(app, "1.1.0")
    autos = list(d.glob("prayer_tracker_업데이트전_v*.db"))
    assert len(autos) == au.KEEP_DB_BACKUPS
    assert user.exists()


# ---------------------------------------------------------------- 8. VERSION 불일치
def test_apply_staged_version_mismatch(monkeypatch, tmp_path, app):
    stage(monkeypatch, tmp_path, app)
    (app / "update" / "staging" / "VERSION").write_text("9.9.9")
    before = snapshot(app)
    assert au.apply(app) == 1
    assert snapshot(app) == before
    assert not (app / "update" / "ready.json").exists()
    assert updater.last_result(app)["ok"] is False


def test_apply_staging_missing(monkeypatch, tmp_path, app):
    stage(monkeypatch, tmp_path, app)
    shutil.rmtree(app / "update" / "staging")
    before = snapshot(app)
    assert au.apply(app) == 1
    assert snapshot(app) == before


# ---------------------------------------------------------------- 9. 중단 후 재실행
def test_apply_rerun_after_interruption_keeps_original_backup(monkeypatch, tmp_path, app):
    before = snapshot(app)
    stage(monkeypatch, tmp_path, app)
    upd = app / "update"
    staging = upd / "staging"
    new, remove = au.plan(app, staging)
    new.sort(key=lambda r: r == "VERSION")
    # 1차 시도: 백업 후 일부 파일만 복사하고 중단된 상황
    au.backup_program(app, upd, "1.0.0", new + remove)
    for rel in new[:3]:
        shutil.copy2(staging / rel, app / rel)
    (app / "prayer_tracker" / "old_module.py").unlink()
    assert (app / "VERSION").read_text() == "1.0.0"

    assert au.apply(app) == 0
    assert (app / "VERSION").read_text() == "1.1.0"
    b = upd / "backup" / "v1.0.0"
    for rel, content in before.items():
        if rel.startswith("data/") or rel == "run.bat":
            continue
        if rel in new or rel in remove:
            assert (b / rel).read_bytes() == content, rel     # 백업은 여전히 원본
    assert not (app / "prayer_tracker" / "old_module.py").exists()


def test_backup_program_adds_files_not_in_earlier_plan(app):
    upd = app / "update"
    au.backup_program(app, upd, "1.0.0", ["prayer_tracker/__init__.py"])
    (app / "prayer_tracker" / "__init__.py").write_bytes(b"# half-written")   # 중단 중 덮어씀
    au.backup_program(app, upd, "1.0.0", ["prayer_tracker/__init__.py", "tools/launcher.ps1"])
    b = upd / "backup" / "v1.0.0"
    assert (b / "prayer_tracker" / "__init__.py").read_bytes() == b"# old init"
    assert (b / "tools" / "launcher.ps1").read_bytes() == b"old launcher"
    m = json.loads((b / "_manifest.json").read_text(encoding="utf-8"))
    assert set(m["existed"]) == {"prayer_tracker/__init__.py", "tools/launcher.ps1"}


# ---------------------------------------------------------------- 10. 실제 배포 zip
def test_extract_package_accepts_real_dist_zip(tmp_path):
    zips = sorted((PROJECT / "dist").glob("기도인증현황_v*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        pytest.skip("dist에 배포 zip이 없음")
    z = zips[-1]
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        if not any(n.endswith("tools/apply_update.py") for n in names):
            pytest.skip("이 zip은 업데이트 기능 이전 버전")
        ver_name = next(n for n in names if n.endswith("/VERSION") and n.count("/") == 1)
        ver = zf.read(ver_name).decode("utf-8-sig").strip()
    files = updater.extract_package(z, tmp_path / "st", ver)
    assert "VERSION" in files and "run.bat" in files
    assert not any(f.startswith("data/") for f in files)


# ---- 버전별 바뀐 점(변경 내역) ----
def test_strip_checksum_removes_sha_lines():
    notes = "## 바뀐 점\n- 개선\n\nSHA256: " + "a" * 64 + "\n"
    assert updater.strip_checksum(notes) == "## 바뀐 점\n- 개선"


def test_parse_changelog_sorts_and_filters():
    data = [
        {"tag_name": "v1.0.2", "published_at": "2026-11-06T10:00:00Z", "body": "- 메뉴\nSHA256: " + "b" * 64},
        {"tag_name": "v1.0.10", "published_at": "2026-12-01T00:00:00Z", "body": "- 열 번째"},
        {"tag_name": "v1.1.0-beta", "body": "형식 다름"},
        {"tag_name": "v1.2.0", "draft": True, "body": "초안"},
        {"tag_name": "v1.3.0", "prerelease": True, "body": "미리보기"},
        {"tag_name": "v1.0.1", "body": None},
        "깨진 항목",
    ]
    out = updater.parse_changelog(data)
    assert [x["version"] for x in out] == ["1.0.10", "1.0.2", "1.0.1"]
    assert out[1] == {"version": "1.0.2", "published_at": "2026-11-06", "notes": "- 메뉴"}
    assert out[2]["notes"] == "" and out[2]["published_at"] == ""
    assert updater.parse_changelog({"message": "Not Found"}) == []


def test_fetch_changelog_network_error_is_friendly(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(updater, "_get", boom)
    with pytest.raises(UpdateError, match="인터넷"):
        updater.fetch_changelog()
