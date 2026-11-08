"""운영 설정. 새로운 정책을 하드코딩하지 않고 설정으로 노출한다."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class Settings(BaseModel):
    # 새벽 유예시간 경계(시). 이 시각 미만에 시작한 세션은 동적 귀속 대상.
    grace_hour: int = 4
    # 추적 시작일. 이 날짜 이전으로 귀속되는 세션은 집계 제외(OUT_OF_RANGE).
    # None이면 가장 이른 데이터의 날짜를 사용한다.
    tracking_start_date: date | None = None
    # 시작~종료가 이보다 길면 자동 매칭하지 않는다(시간).
    max_session_hours: float = 6.0
    # 단독 "마칩니다/마쳤습니다"를 진행 중 세션이 있을 때 자동 확정 (결정 #1)
    auto_confirm_bare_end_in_session: bool = True
    # 단독 "시작합니다"는 기본적으로 검토 대상
    auto_confirm_bare_start: bool = False
    # 단독 "기도합니다"를 같은 사람의 종료 인증이 뒤따를 때(최대 세션 시간 안) 시작으로 자동 확정
    auto_confirm_pray_start_before_end: bool = True
    # 검증된 오타/구어체(MEDIUM)를 정상 문맥에서 자동 확정
    auto_confirm_typo_in_context: bool = True
    # 문장 끝에 붙은 명시적 인증("...가지고 기도 시작합니다")을 정상 문맥에서 자동 확정
    auto_confirm_suffix_in_context: bool = True
    # 퍼지 매칭 최소 유사도(0~100)
    fuzzy_threshold: int = 85
    # 퍼지 매칭은 이 길이(공백 제외) 이하의 짧은 문장에만 적용
    fuzzy_max_len: int = 12
    # 종료 직후 같은 사람의 END가 다시 오면 중복 종료로 본다(분)
    duplicate_end_minutes: int = 30
