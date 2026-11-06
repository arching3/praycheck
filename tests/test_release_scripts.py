"""공개 자동화 스크립트(scripts/package_check.py, ci_release.py) 검사. dist/는 건드리지 않는다."""
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ci_release  # noqa: E402
import package_check  # noqa: E402
from prayer_tracker import updater  # noqa: E402


def make_zip(path: Path, version: str = "1.0.5", extra: dict | None = None) -> Path:
    files = {f: "x" for f in updater.REQUIRED}
    files["VERSION"] = version + "\n"
    files.update(extra or {})
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(f"기도인증현황/{name}", text)
    return path


def test_check_package_ok(tmp_path):
    files = package_check.check_package(make_zip(tmp_path / "a.zip", extra={"data/안내.txt": "x"}), "1.0.5")
    assert "VERSION" in files and not any(f.startswith("data/") for f in files)


@pytest.mark.parametrize("bad", ["data/prayer_tracker.db", "private/대화.txt", "eval/goldset/g.json",
                                 "tests/test_x.py", "runtime/python/python.exe"])
def test_check_package_rejects_private_or_dev_files(tmp_path, bad):
    with pytest.raises(ValueError):
        package_check.check_package(make_zip(tmp_path / "a.zip", extra={bad: "x"}), "1.0.5")


def test_check_package_version_mismatch(tmp_path):
    with pytest.raises(ValueError):
        package_check.check_package(make_zip(tmp_path / "a.zip", version="1.0.4"), "1.0.5")


def test_check_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(package_check, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        package_check.check_notes("1.0.5")                       # 없음
    p = tmp_path / "release_notes" / "v1.0.5.md"
    p.parent.mkdir()
    p.write_text("## 바뀐 점\n", encoding="utf-8")
    with pytest.raises(ValueError):
        package_check.check_notes("1.0.5")                       # 제목만
    p.write_text(f"## 바뀐 점\n- {package_check.PLACEHOLDER}을 적어 주세요)\n", encoding="utf-8")
    with pytest.raises(ValueError):
        package_check.check_notes("1.0.5")                       # 틀 그대로
    p.write_text("## 바뀐 점\n- 검토 화면 개선\n", encoding="utf-8")
    assert "검토 화면 개선" in package_check.check_notes("1.0.5")


def test_ci_release_rejects_tag_version_mismatch(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ci_release.py", "v0.0.0-wrong"])
    monkeypatch.setattr(ci_release, "build", lambda v: pytest.fail("빌드까지 가면 안 됨"))
    assert ci_release.main() == 1
    assert "VERSION" in capsys.readouterr().out
