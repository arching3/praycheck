# CLAUDE.md — 기도 인증 현황 (prayerchecker)

카카오톡 단톡방 내보내기(.txt)에서 기도 시작·종료 인증을 찾아 집계하는 Windows 로컬 Streamlit 앱. 사용자는 개발 경험이 없는 일반인이며, 관리자(이 저장소 주인)가 Claude Code로 개발·배포한다. 요구사항 원문은 `docs/prd.md`, 구조·명령은 `README.md`.

## 대화 방식
- 한국어로 답한다. 결과를 먼저, 짧게. 확인한 것과 확인하지 못한 것을 구분해 말한다.
- 주변 작업(UI, 테스트 작성, 문서, 대량 라벨링 등)은 Sonnet 서브에이전트에 병렬로 맡기고, 판정 엔진(파서·분류·세션·귀속)처럼 까다로운 핵심은 직접 한다. 서브에이전트 결과는 반드시 직접 검증한다.

## 작업 흐름 (반드시 지킬 것)
1. 코드를 고친 뒤 `.venv\Scripts\python -m pytest -q`로 확인한다. 판정 규칙을 바꿨다면 회귀 테스트를 추가한다.
   - 분류 규칙을 바꾸면 메시지 테스트셋(`tests/fixtures/message_set.jsonl` 변형 861개 + 공개하지 않는 익명 실데이터 `eval/goldset/message_set_real.jsonl` 86개)도 함께 돈다. 요약표: `.venv\Scripts\python tests\test_message_set.py`. 새로 잡게 된 문장은 `known_miss`를 지운다.
2. 판정 엔진(분류·세션·귀속)을 바꿨다면 정답셋 평가도 돌려 점수를 비교한다: `.venv\Scripts\python eval\evaluate.py`
   - 기준선(10/10~10/29): 자동 확정 정밀도 100%, 일상 대화 오인정 0건, 잘못된 완료 판정 0건, 일별 상태 일치 96.7%(2026-11-09 "기도합니다" 규칙 후). 이 중 "0건" 지표가 나빠지면 안 된다.
3. UI를 바꿨다면 `streamlit.testing.v1.AppTest`로 모든 페이지가 예외 없이 열리는지, 바꾼 버튼 흐름이 동작하는지 확인한다(DB는 임시 파일로).
4. **배포 zip은 자동으로 갱신된다.** `.claude/settings.json`의 Stop 훅이 답변이 끝날 때마다 `scripts/release.py --hook`을 실행한다(배포 대상 파일이 바뀌었으면 테스트 → `VERSION` 패치 증가 → `dist\기도인증현황_v<버전>.zip`).
   - 훅이 테스트 실패를 돌려주면 zip이 만들어지지 않은 것이다. 원인을 고쳐 다시 통과시킨다.
   - zip을 손으로 만들거나 `VERSION`을 임의로 되돌리지 않는다. 큰 변경일 때만 사용자 요청에 따라 `VERSION`의 major/minor를 올린다.
   - 배포 대상에 새 파일을 추가하면 `scripts/build_dist.py`의 INCLUDE/RENAME과 `scripts/release.py`의 SHIPPED_FILES를 함께 고친다.
5. **사용자에게 새 버전 공개(앱 [업데이트]가 받는 것)**: 관리자가 요청할 때만.
   1. `release_notes/v<버전>.md`에 바뀐 점을 쉬운 말로 쓴다(사용자가 업데이트 화면에서 그대로 읽음).
   2. 커밋 → `scripts/publish.py`(배포 zip 검사, 설명·커밋 상태 확인 후 주석 태그 `v<버전>` 생성).
   3. 관리자에게 `git push --follow-tags`를 안내한다. **push는 하지 않는다**(관리자가 직접).
   4. 태그가 push되면 `.github/workflows/release.yml`이 Windows에서 테스트 → `scripts/ci_release.py`(빌드·검사·SHA256) → Release 등록(latest)까지 자동으로 한다.
   - 원격: `git@github.com:arching3/praycheck.git`(**공개 저장소**). 커밋 전 실명·대화가 섞이지 않았는지 확인한다.
   - 앱은 `releases/latest`만 본다. 태그 push가 곧 사용자 공개다.
6. 화면이 바뀌어 설명서가 낡았으면 `docs/manual/capture.py` → `build_manual.py`로 `docs/사용방법.pdf`를 다시 만든다(Playwright 필요, 데모 데이터만 사용).

## 개인정보 (절대 규칙)
- `private/`(실제 카카오톡 원본, 날짜별대화), `data/`(앱 DB), `eval/goldset/`(실명 포함 정답셋)은 실명·개인 대화를 담고 있다. 커밋·외부 전송·배포 zip·문서·스크린샷·테스트 fixture에 넣지 않는다.
- 테스트 fixture는 `참여자A`처럼 익명으로, 설명서·캡처는 `docs/manual/demo_chat.py`의 가상 인물로만 만든다.
- 사용자 데이터(`data/`, `private/`)나 사용자가 직접 띄운 프로세스·폴더는 묻지 않고 지우거나 덮어쓰지 않는다. 테스트로 만든 흔적은 끝나면 정리한다.

## 확정된 운영 정책 (사용자 결정 — 임의로 바꾸지 말 것)
- 단독 "마칩니다/마쳤습니다/마쳤어요"는 같은 사람의 세션이 진행 중일 때만 END로 자동 확정한다.
- 추적 시작일은 관리자가 필수로 지정한다. 원본은 시작일 하루 전부터만 저장하고, 시작일 이전으로 귀속될 새벽 인증은 집계·검토에서 제외한다(OUT_OF_RANGE).
- "다시 기도 시작합니다"는 재시작: 앞선 시작은 중단(INCOMPLETE, 검토 없음), 재시작 지점부터 새 세션.
- 애매한 오타·퍼지 일치("합미다", "마칩ㄴ다", "무튼 기도합니다")는 검토로 보내는 현재 동작을 유지한다.
- 단독 "기도합니다"는 같은 사람의 다음 인증 메시지가 세션 최대 길이 안의 종료일 때만 시작으로 자동 확정한다(2026-11-09 결정, 설정 `auto_confirm_pray_start_before_end`). 종료가 뒤따르지 않으면 검토.
- 이모티콘 표기 "(별똥별)"은 제거하고 판정, 문장 끝 인증("…가지고 기도 시작합니다")·해요체("기도 마쳤어요")는 인정한다.
- 잘못된 자동 인증보다 관리자 검토를 우선한다. 미완료 세션의 시간은 추정하지 않는다. 관리자 판정·수동 기록은 자동 분석이 덮어쓰지 않는다.
- 카카오톡은 기간 지정 내보내기가 안 되므로 항상 **전체 기간 파일**을 올리는 흐름이다. 날짜별로 나눈 파일은 업로드용이 아니다.

## 구조 요약
- `prayer_tracker/engine.py`는 순수 함수(원본 + 관리자 판정 + 설정 → 결과). UI는 `service.py`만 사용한다.
- 분류 규칙 사전은 `classification/classifier.py` 위쪽(START_HIGH, END_VERB, SUFFIX_*, EXCLUDE 등).
- 업데이트: `prayer_tracker/updater.py`(확인·내려받기·검사 → `update/staging` + `ready.json`까지만) → 다음 실행 때 `launcher.ps1`이 `tools/apply_update.py`로 적용(DB를 `data/backup`에 백업 → 프로그램 파일 백업 → 교체, 실패 시 되돌림). `data/`·`runtime/`·`run.bat`은 바꾸지 않는다.
  - `run.bat`은 실행 중인 배치 파일이라 업데이트로 바꾸지 않는다. 바꿀 일이 있으면 수동 배포가 필요하니 로직은 `launcher.ps1`에 둔다.
  - `apply_update.py`는 표준 라이브러리만 쓴다(교체 대상인 `prayer_tracker`를 import하지 않음).
  - DB 스키마는 `storage/db.py`의 `_migrate`로 **추가만** 한다(열·테이블 삭제·이름 변경 금지). 업데이트된 앱이 옛 DB를 그대로 열어야 한다.
- 실행: `run.bat` → `tools/launcher.ps1`(휴대용 Python 3.13 자동 설치 후 실행). 배포 실행용 의존성은 `requirements-runtime.txt`에 버전 고정.

## Windows에서 겪은 함정
- `.bat`은 ASCII + CRLF로 쓴다(한글 주석·echo 금지, 코드 페이지에 따라 깨짐). 한글 안내는 PowerShell 쪽에서.
- `.ps1`은 UTF-8 **BOM** + CRLF(PowerShell 5.1은 BOM 없는 UTF-8 한글을 깨뜨림). 고친 뒤 `[scriptblock]::Create`로 문법 확인.
- PowerShell 5.1 `Start-Process -PassThru` + 출력 리다이렉트는 `$p.Handle`을 잡아 두지 않으면 ExitCode가 비어 있다.
- `localhost`는 IPv6를 먼저 시도해 약 2초 지연된다. 로컬 서버 확인·접속은 `127.0.0.1`을 쓴다.
- Streamlit 패키지 안에 약 140자 깊이의 경로가 있어, 설치 경로가 길면 260자 제한에 걸린다(launcher는 80자 초과 시 `%LOCALAPPDATA%`에 설치).
- 셸 heredoc·`printf`·파이썬 문자열 안의 역슬래시 경로(`\r`, `\b`, `\S`)가 자주 깨졌다. 경로가 들어간 파일 수정은 Write/Edit 도구를 쓰거나 패치 스크립트를 파일로 만들어 실행하고, 수정 후 결과를 확인한다.
- 콘솔 출력은 cp949라 이모지·일부 한글이 깨질 수 있다: 파이썬 실행 시 `PYTHONIOENCODING=utf-8`.
- 파일 이름이 `-`로 시작하면 명령 옵션으로 오인된다. 그런 이름을 만들지 않는다.
