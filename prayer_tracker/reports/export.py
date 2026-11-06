"""CSV / Excel 내보내기."""
from __future__ import annotations

import io

import pandas as pd


def to_csv_bytes(rows: list[dict]) -> bytes:
    """Excel에서 한글이 깨지지 않도록 BOM 포함 UTF-8."""
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")


def to_excel_bytes(sheets: dict[str, list[dict]]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(w, sheet_name=name[:31], index=False)
    return buf.getvalue()
