"""전체기간대화내용.txt를 날짜별 텍스트 파일로 나눕니다."""
from __future__ import annotations

import re
import sys
from pathlib import Path


DATE_LINE = re.compile(r"^-+\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*\S*요일\s*-+\s*$")


def split_by_date(source: Path, output_dir: Path) -> int:
    text = source.read_text(encoding="utf-8-sig")
    output_dir.mkdir(parents=True, exist_ok=True)

    current_name: str | None = None
    current_lines: list[str] = []
    saved = 0

    def save_current() -> None:
        nonlocal saved
        if current_name is not None:
            (output_dir / current_name).write_text(
                "\n".join(current_lines).rstrip() + "\n", encoding="utf-8"
            )
            saved += 1

    for line in text.splitlines():
        match = DATE_LINE.match(line.strip())
        if match:
            save_current()
            year, month, day = map(int, match.groups())
            current_name = f"{year}년{month}월{day}일.txt"
            current_lines = [line]
        elif current_name is not None:
            current_lines.append(line)

    save_current()
    return saved


if __name__ == "__main__":
    default = Path(__file__).resolve().parent.parent / "private" / "전체기간대화내용.txt"
    input_file = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    destination = input_file.resolve().parent / "날짜별대화"
    count = split_by_date(input_file, destination)
    print(f"{count}개 날짜 파일을 저장했습니다: {destination}")
