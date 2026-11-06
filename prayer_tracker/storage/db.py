"""SQLite 스키마. 원본(source_file/message), 관리자 입력(admin_*), 파생 결과(prayer_*, review_item, day_status)를 분리한다.
파생 테이블은 재계산마다 통째로 다시 쓴다."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS member (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    is_target INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS member_alias (
    alias TEXT PRIMARY KEY,               -- 카카오톡 닉네임(sender_raw)
    member_id INTEGER NOT NULL REFERENCES member(id)
);
CREATE TABLE IF NOT EXISTS source_file (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    imported_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    coverage_start TEXT,                  -- 첫 날짜 구분선 00:00
    first_message_at TEXT,
    last_message_at TEXT,
    coverage_end TEXT,                    -- '저장한 날짜'(없으면 마지막 메시지)
    stored_from TEXT,                     -- 이 시각 이후 메시지만 저장(추적 시작일 하루 전)
    skipped_count INTEGER,                -- 저장 범위 이전이라 건너뛴 메시지 수
    parse_status TEXT NOT NULL,
    encoding TEXT,
    message_count INTEGER,
    new_message_count INTEGER,
    issues TEXT                           -- JSON
);
CREATE TABLE IF NOT EXISTS message (
    id TEXT PRIMARY KEY,                  -- deduplication_key
    source_file_id INTEGER NOT NULL REFERENCES source_file(id),   -- 최초 수집 파일
    sender_raw TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT NOT NULL,
    message_type TEXT NOT NULL,
    source_position INTEGER,
    parse_status TEXT NOT NULL DEFAULT 'OK'
);
CREATE INDEX IF NOT EXISTS ix_message_sent ON message(sent_at);
CREATE TABLE IF NOT EXISTS message_source (   -- 같은 메시지가 여러 파일에 등장할 수 있음
    message_id TEXT NOT NULL REFERENCES message(id),
    source_file_id INTEGER NOT NULL REFERENCES source_file(id),
    source_position INTEGER,
    PRIMARY KEY (message_id, source_file_id)
);

-- 관리자 판정 (재분석이 덮어쓰지 않음)
CREATE TABLE IF NOT EXISTS admin_label (
    message_id TEXT PRIMARY KEY REFERENCES message(id),
    event_type TEXT NOT NULL,             -- START / END / OTHER
    decided_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS admin_link (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_message_id TEXT NOT NULL UNIQUE,
    end_message_id TEXT NOT NULL UNIQUE,
    decided_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS admin_date (
    start_message_id TEXT PRIMARY KEY,
    prayer_date TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS admin_review (
    review_key TEXT PRIMARY KEY,
    status TEXT NOT NULL,                 -- HELD / RESOLVED / NO_CANDIDATE
    note TEXT,
    decided_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS manual_record (      -- 관리자 수동 기도 기록(메시지 없이 완료로 집계)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES member(id),
    prayer_date TEXT NOT NULL,            -- 인증 귀속 날짜
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    previous_value TEXT,
    new_value TEXT,
    changed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    changed_by TEXT NOT NULL DEFAULT 'admin'
);

-- 파생 결과 (재계산 시 교체)
CREATE TABLE IF NOT EXISTS prayer_event (
    message_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    candidate TEXT,
    confidence_level TEXT NOT NULL,
    classification_source TEXT NOT NULL,
    matched_rule TEXT,
    normalized_text TEXT,
    review_status TEXT
);
CREATE TABLE IF NOT EXISTS prayer_session (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    start_message_id TEXT,
    end_message_id TEXT,
    start_at TEXT,
    end_at TEXT,
    duration_seconds INTEGER,
    prayer_date TEXT,
    status TEXT NOT NULL,
    date_assignment_source TEXT,
    manual INTEGER NOT NULL DEFAULT 0,
    manual_record_id INTEGER
);
CREATE TABLE IF NOT EXISTS review_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_key TEXT NOT NULL,
    member_id INTEGER,
    session_key TEXT,
    target_date TEXT,
    review_type TEXT NOT NULL,
    candidate_message_ids TEXT NOT NULL,  -- JSON
    reason TEXT,
    status TEXT NOT NULL,
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS day_status (
    member_id INTEGER NOT NULL,
    prayer_date TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (member_id, prayer_date)
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """이전 버전 DB에 새 컬럼을 추가한다."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(source_file)")}
    for name, typ in (("coverage_end", "TEXT"), ("stored_from", "TEXT"), ("skipped_count", "INTEGER")):
        if name not in cols:
            conn.execute(f"ALTER TABLE source_file ADD COLUMN {name} {typ}")
    if "manual_record_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(prayer_session)")}:
        conn.execute("ALTER TABLE prayer_session ADD COLUMN manual_record_id INTEGER")
    conn.commit()
