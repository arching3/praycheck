"""애플리케이션 서비스: 업로드, 참여자 관리, 관리자 판정, 재계산. UI는 이 계층만 사용한다."""
from __future__ import annotations

import bisect
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from prayer_tracker.config import Settings
from prayer_tracker.engine import AdminDecisions, analyze, tracking_start_of
from prayer_tracker.ingestion.parser import file_hash, parse_bytes
from prayer_tracker.models import (
    AnalysisResult, Coverage, EventType, ManualRecord, Message, MessageType,
)
from prayer_tracker.storage.db import connect

# 환경변수 PRAYER_TRACKER_DB로 다른 DB 파일을 쓸 수 있다(데모·백업 확인용)
DEFAULT_DB = Path(os.environ.get("PRAYER_TRACKER_DB")
                  or Path(__file__).resolve().parent.parent / "data" / "prayer_tracker.db")
_FMT = "%Y-%m-%d %H:%M:%S"


def _dt(s: str | None) -> datetime | None:
    return datetime.strptime(s, _FMT) if s else None


@dataclass
class ImportReport:
    filename: str
    status: str                 # OK / DUPLICATE_FILE / EMPTY / NEED_START_DATE / BEFORE_START
    total_messages: int = 0
    new_messages: int = 0
    new_senders: list[str] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    encoding: str = ""
    skipped_before_start: int = 0       # 추적 시작일 하루 전보다 이른 메시지(저장 안 함)
    saved_at: datetime | None = None    # 파일의 '저장한 날짜'


class PrayerService:
    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self.db_path = Path(db_path) if str(db_path) != ":memory:" else db_path
        self.conn = connect(db_path)
        self._result: AnalysisResult | None = None
        # 메시지는 재계산 때만 DB에서 다시 읽는다(모든 변경 작업이 recompute를 거친다).
        self._messages: list[Message] | None = None
        self._by_id: dict[str, Message] = {}

    # ---------------------------------------------------------------- 설정
    def get_settings(self) -> Settings:
        row = self.conn.execute("SELECT value FROM setting WHERE key='settings'").fetchone()
        return Settings.model_validate_json(row["value"]) if row else Settings()

    def save_settings(self, settings: Settings) -> None:
        prev = self.get_settings()
        self.conn.execute("INSERT OR REPLACE INTO setting(key,value) VALUES('settings',?)",
                          (settings.model_dump_json(),))
        self._audit("setting", "settings", "update", prev.model_dump_json(), settings.model_dump_json())
        self.conn.commit()
        self.recompute()

    # ---------------------------------------------------------------- 업로드
    def storage_cutoff(self, settings: Settings | None = None) -> datetime | None:
        """이 시각 이전의 메시지는 저장하지 않는다: 추적 시작일 하루 전 00:00 (전날 문맥 확인용)."""
        tsd = (settings or self.get_settings()).tracking_start_date
        return datetime.combine(tsd - timedelta(days=1), time(0)) if tsd else None

    def import_file(self, filename: str, data: bytes) -> ImportReport:
        """카카오톡 '전체 기간' 내보내기 파일을 그대로 받는다. 이미 있는 메시지는 건너뛰고 새 메시지만 추가한다."""
        cutoff = self.storage_cutoff()
        if cutoff is None:
            return ImportReport(filename, "NEED_START_DATE")
        h = file_hash(data)
        prev = self.conn.execute("SELECT id, stored_from FROM source_file WHERE file_hash=?", (h,)).fetchone()
        if prev and prev["stored_from"] and _dt(prev["stored_from"]) <= cutoff:
            return ImportReport(filename, "DUPLICATE_FILE")
        parsed = parse_bytes(data)
        if not parsed.messages:
            return ImportReport(filename, "EMPTY", issues=[i.__dict__ for i in parsed.issues],
                                encoding=parsed.encoding)
        keep = [m for m in parsed.messages if m.sent_at >= cutoff]
        skipped = len(parsed.messages) - len(keep)
        if not keep:
            return ImportReport(filename, "BEFORE_START", len(parsed.messages), skipped_before_start=skipped,
                                encoding=parsed.encoding)
        issues = [i.__dict__ for i in parsed.issues]
        cov_start = max(datetime.combine(parsed.first_date, time(0)), cutoff)
        cov_end = max(parsed.last_message_at, parsed.saved_at or parsed.last_message_at)
        vals = (filename, cov_start.strftime(_FMT), min(m.sent_at for m in keep).strftime(_FMT),
                parsed.last_message_at.strftime(_FMT), cov_end.strftime(_FMT), cutoff.strftime(_FMT),
                "WARN" if issues else "OK", parsed.encoding, len(parsed.messages), skipped,
                json.dumps(issues, ensure_ascii=False))
        if prev:
            # 추적 시작일을 앞당긴 뒤 같은 파일을 다시 올린 경우: 모자란 앞부분만 채운다
            fid = prev["id"]
            self.conn.execute(
                "UPDATE source_file SET filename=?,coverage_start=?,first_message_at=?,last_message_at=?,"
                "coverage_end=?,stored_from=?,parse_status=?,encoding=?,message_count=?,skipped_count=?,issues=?,"
                "imported_at=datetime('now','localtime') WHERE id=?", (*vals, fid))
        else:
            fid = self.conn.execute(
                "INSERT INTO source_file(filename,coverage_start,first_message_at,last_message_at,coverage_end,"
                "stored_from,parse_status,encoding,message_count,skipped_count,issues,file_hash) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (*vals, h)).lastrowid
        new = 0
        known = {r["alias"] for r in self.conn.execute("SELECT alias FROM member_alias")}
        new_senders = []
        for m in keep:
            c = self.conn.execute(
                "INSERT OR IGNORE INTO message(id,source_file_id,sender_raw,sent_at,seq,raw_text,message_type,"
                "source_position,parse_status) VALUES(?,?,?,?,?,?,?,?,?)",
                (m.id, fid, m.sender_raw, m.sent_at.strftime(_FMT), m.seq, m.raw_text,
                 m.message_type.value, m.source_position, m.parse_status))
            new += c.rowcount
            self.conn.execute("INSERT OR IGNORE INTO message_source VALUES(?,?,?)", (m.id, fid, m.source_position))
            if m.sender_raw not in known:
                # 새 닉네임은 '대상 아님'으로 등록. 대상자 지정은 관리자가 한다(PRD 2.1).
                mid = self.conn.execute("INSERT INTO member(display_name,is_target) VALUES(?,0)",
                                        (m.sender_raw,)).lastrowid
                self.conn.execute("INSERT INTO member_alias VALUES(?,?)", (m.sender_raw, mid))
                known.add(m.sender_raw)
                new_senders.append(m.sender_raw)
        self.conn.execute("UPDATE source_file SET new_message_count=? WHERE id=?", (new, fid))
        self._audit("source_file", str(fid), "reimport" if prev else "import", None,
                    json.dumps({"filename": filename, "messages": len(parsed.messages), "new": new,
                                "skipped_before_start": skipped}, ensure_ascii=False))
        self.conn.commit()
        self.recompute()
        return ImportReport(filename, "OK", len(parsed.messages), new, new_senders, issues, parsed.encoding,
                            skipped_before_start=skipped, saved_at=parsed.saved_at)

    def count_before_cutoff(self) -> int:
        cutoff = self.storage_cutoff()
        if cutoff is None:
            return 0
        return self.conn.execute("SELECT COUNT(*) AS n FROM message WHERE sent_at < ?",
                                 (cutoff.strftime(_FMT),)).fetchone()["n"]

    def purge_before_cutoff(self) -> int:
        """추적 시작일을 늦춘 뒤, 저장 범위 밖이 된 원본 메시지와 그 판정을 삭제한다(PRD 14.2)."""
        cutoff = self.storage_cutoff()
        if cutoff is None:
            return 0
        c, cut = self.conn, cutoff.strftime(_FMT)
        old = "SELECT id FROM message WHERE sent_at < ?"
        c.execute(f"DELETE FROM admin_label WHERE message_id IN ({old})", (cut,))
        c.execute(f"DELETE FROM admin_link WHERE start_message_id IN ({old}) OR end_message_id IN ({old})",
                  (cut, cut))
        c.execute(f"DELETE FROM admin_date WHERE start_message_id IN ({old})", (cut,))
        c.execute(f"DELETE FROM message_source WHERE message_id IN ({old})", (cut,))
        n = c.execute("DELETE FROM message WHERE sent_at < ?", (cut,)).rowcount
        c.execute("UPDATE source_file SET coverage_start=MAX(coverage_start, ?), "
                  "stored_from=MAX(COALESCE(stored_from, ?), ?)", (cut, cut, cut))
        self._audit("message", "before:" + cut, "purge", None, str(n))
        c.commit()
        self.recompute()
        return n

    def source_files(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM source_file ORDER BY imported_at")]

    def last_import_at(self) -> str | None:
        r = self.conn.execute("SELECT MAX(imported_at) AS t FROM source_file").fetchone()
        return r["t"]

    # ---------------------------------------------------------------- 참여자
    def members(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT m.*, GROUP_CONCAT(a.alias, ', ') AS aliases, "
            "(SELECT COUNT(*) FROM message WHERE sender_raw IN "
            " (SELECT alias FROM member_alias WHERE member_id=m.id)) AS message_count "
            "FROM member m LEFT JOIN member_alias a ON a.member_id=m.id "
            "WHERE m.is_active=1 GROUP BY m.id ORDER BY m.display_name").fetchall()
        return [dict(r) for r in rows]

    def member_names(self) -> dict[int, str]:
        return {r["id"]: r["display_name"] for r in self.conn.execute("SELECT id, display_name FROM member")}

    def set_targets(self, target_ids: set[int]) -> None:
        for r in self.conn.execute("SELECT id, is_target FROM member").fetchall():
            want = 1 if r["id"] in target_ids else 0
            if r["is_target"] != want:
                self.conn.execute("UPDATE member SET is_target=? WHERE id=?", (want, r["id"]))
                self._audit("member", str(r["id"]), "set_target", str(r["is_target"]), str(want))
        self.conn.commit()
        self.recompute()

    def rename_member(self, member_id: int, name: str) -> None:
        prev = self.member_names().get(member_id)
        self.conn.execute("UPDATE member SET display_name=? WHERE id=?", (name, member_id))
        self._audit("member", str(member_id), "rename", prev, name)
        self.conn.commit()

    def merge_member(self, source_id: int, into_id: int) -> None:
        """닉네임 변경 대응: source의 별칭을 into로 옮기고 source를 비활성화."""
        if source_id == into_id:
            return
        self.conn.execute("UPDATE member_alias SET member_id=? WHERE member_id=?", (into_id, source_id))
        self.conn.execute("UPDATE member SET is_active=0, is_target=0 WHERE id=?", (source_id,))
        self._audit("member", str(source_id), "merge", str(source_id), str(into_id))
        self.conn.commit()
        self.recompute()

    # ---------------------------------------------------------------- 관리자 판정
    def label_message(self, message_id: str, event_type: EventType | None) -> None:
        """event_type=None이면 관리자 지정 해제(자동 판정으로 복귀)."""
        prev = self.conn.execute("SELECT event_type FROM admin_label WHERE message_id=?", (message_id,)).fetchone()
        if event_type is None:
            self.conn.execute("DELETE FROM admin_label WHERE message_id=?", (message_id,))
        else:
            self.conn.execute("INSERT OR REPLACE INTO admin_label(message_id,event_type) VALUES(?,?)",
                              (message_id, event_type.value))
        self._audit("message", message_id, "label", prev["event_type"] if prev else None,
                    event_type.value if event_type else None)
        self.conn.commit()
        self.recompute()

    def link_messages(self, start_id: str, end_id: str) -> None:
        self.conn.execute("DELETE FROM admin_link WHERE start_message_id IN (?,?) OR end_message_id IN (?,?)",
                          (start_id, end_id, start_id, end_id))
        self.conn.execute("INSERT INTO admin_link(start_message_id,end_message_id) VALUES(?,?)", (start_id, end_id))
        self._audit("session", f"{start_id}->{end_id}", "link", None, json.dumps([start_id, end_id]))
        self.conn.commit()
        self.recompute()

    def unlink(self, start_id: str) -> None:
        self.conn.execute("DELETE FROM admin_link WHERE start_message_id=?", (start_id,))
        self._audit("session", start_id, "unlink", start_id, None)
        self.conn.commit()
        self.recompute()

    def set_session_date(self, start_message_id: str, d: date | None) -> None:
        prev = self.conn.execute("SELECT prayer_date FROM admin_date WHERE start_message_id=?",
                                 (start_message_id,)).fetchone()
        if d is None:
            self.conn.execute("DELETE FROM admin_date WHERE start_message_id=?", (start_message_id,))
        else:
            self.conn.execute("INSERT OR REPLACE INTO admin_date(start_message_id,prayer_date) VALUES(?,?)",
                              (start_message_id, d.isoformat()))
        self._audit("session_date", start_message_id, "set_date", prev["prayer_date"] if prev else None,
                    d.isoformat() if d else None)
        self.conn.commit()
        self.recompute()

    def set_review_status(self, review_key: str, status: str | None, note: str = "") -> None:
        """status: HELD(보류) / NO_CANDIDATE(올바른 후보 없음) / RESOLVED / None(다시 열기)."""
        prev = self.conn.execute("SELECT status FROM admin_review WHERE review_key=?", (review_key,)).fetchone()
        if status is None:
            self.conn.execute("DELETE FROM admin_review WHERE review_key=?", (review_key,))
        else:
            self.conn.execute("INSERT OR REPLACE INTO admin_review(review_key,status,note) VALUES(?,?,?)",
                              (review_key, status, note))
        self._audit("review", review_key, "status", prev["status"] if prev else None, status)
        self.conn.commit()
        self.recompute()

    def decisions(self) -> AdminDecisions:
        c = self.conn
        return AdminDecisions(
            labels={r["message_id"]: EventType(r["event_type"]) for r in c.execute("SELECT * FROM admin_label")},
            links=[(r["start_message_id"], r["end_message_id"]) for r in c.execute("SELECT * FROM admin_link")],
            date_overrides={r["start_message_id"]: date.fromisoformat(r["prayer_date"])
                            for r in c.execute("SELECT * FROM admin_date")},
            review_status={r["review_key"]: r["status"] for r in c.execute("SELECT * FROM admin_review")},
            manual_records=self.manual_records(),
        )

    # ---------------------------------------------------------------- 수동 기록 (CRUD)
    @staticmethod
    def _validate_manual(prayer_date: date, start_at: datetime, end_at: datetime) -> None:
        if end_at <= start_at:
            raise ValueError("종료 시각은 시작 시각보다 늦어야 합니다.")
        if end_at - start_at > timedelta(hours=24):
            raise ValueError("기도 시간이 24시간을 넘을 수 없습니다.")
        if abs((start_at.date() - prayer_date).days) > 1:
            raise ValueError("시작 시각은 인증 날짜의 전날~다음 날 사이여야 합니다.")

    def _manual_dict(self, record_id: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM manual_record WHERE id=?", (record_id,)).fetchone()
        return dict(r) if r else None

    def manual_records(self, member_id: int | None = None) -> list[ManualRecord]:
        q, args = "SELECT * FROM manual_record", ()
        if member_id is not None:
            q, args = q + " WHERE member_id=?", (member_id,)
        return [ManualRecord(r["id"], r["member_id"], date.fromisoformat(r["prayer_date"]), _dt(r["start_at"]),
                             _dt(r["end_at"]), r["note"])
                for r in self.conn.execute(q + " ORDER BY prayer_date DESC, start_at DESC", args)]

    def create_manual_record(self, member_id: int, prayer_date: date, start_at: datetime, end_at: datetime,
                             note: str = "") -> int:
        self._validate_manual(prayer_date, start_at, end_at)
        rid = self.conn.execute(
            "INSERT INTO manual_record(member_id,prayer_date,start_at,end_at,note) VALUES(?,?,?,?,?)",
            (member_id, prayer_date.isoformat(), start_at.strftime(_FMT), end_at.strftime(_FMT), note)).lastrowid
        self._audit("manual_record", str(rid), "create", None, json.dumps(self._manual_dict(rid), ensure_ascii=False))
        self.conn.commit()
        self.recompute()
        return rid

    def update_manual_record(self, record_id: int, member_id: int, prayer_date: date, start_at: datetime,
                             end_at: datetime, note: str = "") -> None:
        prev = self._manual_dict(record_id)
        if prev is None:
            raise KeyError(f"수동 기록 {record_id}이(가) 없습니다.")
        self._validate_manual(prayer_date, start_at, end_at)
        self.conn.execute(
            "UPDATE manual_record SET member_id=?,prayer_date=?,start_at=?,end_at=?,note=?,"
            "updated_at=datetime('now','localtime') WHERE id=?",
            (member_id, prayer_date.isoformat(), start_at.strftime(_FMT), end_at.strftime(_FMT), note, record_id))
        self._audit("manual_record", str(record_id), "update", json.dumps(prev, ensure_ascii=False),
                    json.dumps(self._manual_dict(record_id), ensure_ascii=False))
        self.conn.commit()
        self.recompute()

    def delete_manual_record(self, record_id: int) -> dict | None:
        """삭제한 기록을 돌려준다(되돌리기용)."""
        prev = self._manual_dict(record_id)
        if prev is None:
            return None
        self.conn.execute("DELETE FROM manual_record WHERE id=?", (record_id,))
        self._audit("manual_record", str(record_id), "delete", json.dumps(prev, ensure_ascii=False), None)
        self.conn.commit()
        self.recompute()
        return prev

    def audit_log(self, limit: int = 500) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]

    # ---------------------------------------------------------------- 조회
    def load_messages(self) -> list[Message]:
        if self._messages is None:
            self._messages = self._read_messages()
            self._by_id = {m.id: m for m in self._messages}
        return self._messages

    def _read_messages(self) -> list[Message]:
        alias = {r["alias"]: r["member_id"] for r in self.conn.execute("SELECT * FROM member_alias")}
        return [Message(id=r["id"], sender_raw=r["sender_raw"], sent_at=_dt(r["sent_at"]), raw_text=r["raw_text"],
                        message_type=MessageType(r["message_type"]), source_file_id=r["source_file_id"],
                        source_position=r["source_position"], seq=r["seq"],
                        member_id=alias.get(r["sender_raw"]), parse_status=r["parse_status"])
                for r in self.conn.execute("SELECT * FROM message ORDER BY sent_at, seq")]

    def coverage(self) -> list[Coverage]:
        # 수집 범위의 끝은 '저장한 날짜'(없으면 마지막 메시지 시각)
        return [Coverage(_dt(r["coverage_start"]), _dt(r["coverage_end"] or r["last_message_at"]))
                for r in self.conn.execute("SELECT coverage_start, coverage_end, last_message_at FROM source_file")]

    def targets(self) -> set[int]:
        return {r["id"] for r in self.conn.execute("SELECT id FROM member WHERE is_target=1 AND is_active=1")}

    def tracking_start(self) -> date | None:
        return tracking_start_of(self.get_settings(), self.coverage())

    def messages_by_id(self) -> dict[str, Message]:
        self.load_messages()
        return self._by_id

    def context_messages(self, center: datetime, member_id: int | None = None,
                         minutes: int = 60) -> list[Message]:
        lo, hi = center - timedelta(minutes=minutes), center + timedelta(minutes=minutes)
        msgs = self.load_messages()
        i = bisect.bisect_left(msgs, lo, key=lambda m: m.sent_at)
        j = bisect.bisect_right(msgs, hi, key=lambda m: m.sent_at)
        return [m for m in msgs[i:j] if member_id is None or m.member_id == member_id]

    # ---------------------------------------------------------------- 재계산
    def recompute(self) -> AnalysisResult:
        self._messages = None
        res = analyze(self.load_messages(), self.targets(), self.coverage(), self.decisions(), self.get_settings())
        c = self.conn
        c.execute("DELETE FROM prayer_event"); c.execute("DELETE FROM prayer_session")
        c.execute("DELETE FROM review_item"); c.execute("DELETE FROM day_status")
        reviewed = {mid for r in res.reviews if r.status in ("OPEN", "HELD") for mid in r.message_ids}
        c.executemany("INSERT INTO prayer_event VALUES(?,?,?,?,?,?,?,?)", [
            (e.message_id, e.event_type.value, e.candidate.value if e.candidate else None, e.confidence.value,
             e.source.value, e.matched_rule, e.normalized_text, "PENDING" if e.message_id in reviewed else None)
            for e in res.events.values()])
        c.executemany(
            "INSERT INTO prayer_session(member_id,start_message_id,end_message_id,start_at,end_at,duration_seconds,"
            "prayer_date,status,date_assignment_source,manual,manual_record_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
                (s.member_id, s.start_message_id, s.end_message_id,
                 s.start_at.strftime(_FMT) if s.start_at else None, s.end_at.strftime(_FMT) if s.end_at else None,
                 s.duration_seconds, s.prayer_date.isoformat() if s.prayer_date else None, s.status.value,
                 s.date_source.value if s.date_source else None, int(s.manual), s.manual_id)
                for s in res.sessions])
        c.executemany(
            "INSERT INTO review_item(review_key,member_id,session_key,target_date,review_type,candidate_message_ids,"
            "reason,status) VALUES(?,?,?,?,?,?,?,?)", [
                (r.key, r.member_id, r.session_key, r.target_date.isoformat() if r.target_date else None,
                 r.review_type.value, json.dumps(r.message_ids), r.reason, r.status) for r in res.reviews])
        c.executemany("INSERT INTO day_status VALUES(?,?,?)",
                      [(m, d.isoformat(), s.value) for (m, d), s in res.day_status.items()])
        c.commit()
        self._result = res
        return res

    @property
    def result(self) -> AnalysisResult:
        return self._result or self.recompute()

    # ---------------------------------------------------------------- 데이터 관리
    def delete_all_data(self) -> None:
        """원본 메시지와 모든 판정을 삭제한다(개인정보 보호, PRD 14.2). 참여자 설정은 유지."""
        for t in ("prayer_event", "prayer_session", "review_item", "day_status", "admin_label", "admin_link",
                  "admin_date", "admin_review", "manual_record", "message_source", "message", "source_file"):
            self.conn.execute(f"DELETE FROM {t}")
        self._audit("database", "all", "delete_data", None, None)
        self.conn.commit()
        self._result = None
        self._messages = None

    def _audit(self, entity_type, entity_id, action, prev, new):
        self.conn.execute("INSERT INTO audit_log(entity_type,entity_id,action,previous_value,new_value) "
                          "VALUES(?,?,?,?,?)", (entity_type, entity_id, action, prev, new))
