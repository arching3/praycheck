# 기도 인증 현황 (prayerchecker)

카카오톡 단체 대화방 내보내기(.txt)에서 참여자별 "기도 시작/종료" 메시지를 찾아 날짜별 인증 현황을 집계하는 로컬 Windows 앱입니다. 판정이 애매한 경우만 관리자가 검토 화면에서 확인·지정합니다.

- 사용자 설명서: [`docs/사용방법.pdf`](docs/사용방법.pdf)
- 요구사항 문서: [`docs/prd.md`](docs/prd.md)

## 실행 (일반 사용자)
`run.bat`을 더블클릭하면 됩니다. 따로 설치할 것은 없습니다.
- 처음 실행할 때 휴대용 Python 3.13과 구성 요소(`requirements-runtime.txt`, 버전 고정)를 내려받습니다. 인터넷이 필요하고 3~10분 걸리며, 관리자 권한이나 PC 설정 변경은 없습니다.
  - 설치 위치는 보통 프로그램 폴더 안 `runtime\`입니다. 폴더 경로가 길면(80자 초과) Windows 경로 길이 제한을 피하려고 `%LOCALAPPDATA%\PrayerTracker\rt-<해시>\`에 설치합니다.
- 준비가 끝나면 서버를 `127.0.0.1`에 띄우고, 응답하면 브라우저를 엽니다. 8501번 포트가 사용 중이면 다음 포트를 씁니다.
- 실제 동작은 `tools\launcher.ps1`이 합니다. 오류 내용은 설치 위치의 `setup.log`, `server.err.log`에 남습니다.
- `requirements-runtime.txt`가 바뀌면 다음 실행 때 구성 요소를 다시 설치합니다. 설치 위치 폴더를 지우면 처음부터 다시 준비합니다.

카카오톡 대화는 PC 카카오톡 → 대화방 메뉴(≡) → 설정 → **대화 내용 내보내기** → **텍스트만 보내기**로 받아, 앱의 **업로드**에 **전체 파일 그대로** 올립니다. 이미 반영된 메시지는 건너뛰고 새 메시지만 추가됩니다. 날짜별로 나눈 파일은 수집 범위가 끊겨 새벽 인증의 날짜를 판단하지 못하므로 올리지 마세요.

## 폴더 구조
```
prayerchecker/
├─ run.bat                    실행(첫 실행 시 자동 준비)
├─ VERSION                    배포 버전(자동 증가)
├─ requirements.txt           개발용 의존성
├─ requirements-runtime.txt   배포 실행용 의존성(버전 고정)
├─ prayer_tracker/            앱 소스
│  ├─ ingestion/              카카오톡 TXT 파서
│  ├─ classification/         인증 표현 분류(규칙·오타·퍼지)
│  ├─ sessions/               개인별 시작·종료 연결(상태 머신)
│  ├─ assignment/             04:00 날짜 귀속
│  ├─ storage/                SQLite 스키마
│  ├─ reports/                집계, CSV·Excel, PDF 보고서(템플릿)
│  ├─ ui/                     Streamlit 화면
│  ├─ updater.py              새 버전 확인·내려받기·준비(GitHub Release)
│  ├─ engine.py               분석 파이프라인(순수 함수)
│  └─ service.py              업로드·판정·수동 기록·재계산(UI가 쓰는 유일한 계층)
├─ tools/launcher.ps1         run.bat이 호출하는 실행기(배포에 포함)
├─ tools/apply_update.py      준비된 업데이트 적용기(launcher가 실행, 배포에 포함)
├─ tests/                     단위·통합 테스트(익명 fixture)
├─ eval/                      정답셋 대비 성능 평가(정답셋 goldset/은 커밋 금지)
├─ scripts/                   개발용 도구
│  ├─ release.py / .bat       변경 감지 → 테스트 → 버전 올리기 → 배포 zip (훅이 자동 실행)
│  ├─ build_dist.py           배포 zip 만들기
│  ├─ publish.py              GitHub Release에 올릴 파일 준비·검사
│  ├─ split_chat_by_date.py   전체 대화를 날짜별 파일로 나누기(평가·열람용)
│  └─ parsing.bat             위 분할 스크립트 실행
├─ docs/
│  ├─ prd.md                  요구사항
│  ├─ 사용방법.pdf            사용자 설명서
│  ├─ 처음 읽어 주세요.txt    배포 zip에 들어가는 안내문
│  └─ manual/                 설명서 생성(데모 대화, 화면 캡처, PDF 빌드)
├─ private/                   (커밋 금지) 실제 카카오톡 원본, 날짜별대화/
├─ data/                      (커밋 금지) 앱 DB prayer_tracker.db
└─ dist/                      (커밋 금지) 배포 zip
```

## 개발
### 환경
```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run prayer_tracker\ui\app.py
```
앱이 다른 DB 파일을 쓰게 하려면 환경변수 `PRAYER_TRACKER_DB`에 경로를 지정합니다.

### 테스트
```bat
.venv\Scripts\python -m pytest
```

### 성능 평가
`private/날짜별대화/`의 10/10~10/29 대화와 정답셋(`eval/goldset/`)으로 파서·분류·세션·날짜 귀속을 채점합니다.
```bat
.venv\Scripts\python eval\evaluate.py               :: 하나의 내보내기 파일로 분석
.venv\Scripts\python eval\evaluate.py --per-day-files
```
리포트는 `eval/goldset/report*.md`에 저장됩니다(실명 포함).

### 사용 설명서 다시 만들기
화면 캡처는 가상 인물의 데모 대화(`docs/manual/demo_chat.py`)로 앱을 띄워 자동으로 찍습니다. 실제 대화는 쓰지 않습니다. 브라우저는 PC에 설치된 Edge를 사용합니다.
```bat
.venv\Scripts\python -m pip install playwright
.venv\Scripts\python docs\manual\capture.py %TEMP%\prayer_manual
.venv\Scripts\python docs\manual\build_manual.py
```

### 배포 zip 만들기 (자동)
소스를 고치면 배포 zip까지 자동으로 갱신됩니다.
- **Claude Code로 작업할 때:** `.claude/settings.json`의 Stop 훅이 Claude가 답변을 마칠 때마다 `scripts/release.py --hook`을 실행합니다.
- **직접 고쳤을 때:** `scripts\release.bat`을 더블클릭합니다(`--force`를 붙이면 변경이 없어도 다시 빌드).

`release.py`가 하는 일:
1. 배포 대상(`prayer_tracker/**.py`, `run.bat`, `tools/launcher.ps1`, `tools/apply_update.py`, `requirements-runtime.txt`, `docs/사용방법.pdf`, `docs/처음 읽어 주세요.txt`)의 지문을 `dist/.build_state.json`과 비교해, 바뀐 것이 없으면 바로 끝냅니다.
2. 바뀌었으면 테스트를 돌립니다. 실패하면 zip을 만들지 않습니다. 훅에서는 실패 내용을 Claude에게 돌려줘 고치게 하고, 같은 실패가 반복되면 경고만 남깁니다.
3. 통과하면 `VERSION`의 패치 번호를 올리고(1.0.0 → 1.0.1) `dist\기도인증현황_v<버전>.zip`을 만듭니다. 큰 변경은 `VERSION`을 직접 고치면 그 번호를 씁니다.
4. 최근 zip 5개만 남기고, `dist\빌드기록.txt`에 버전·테스트 결과·바뀐 파일을 기록합니다.

zip에는 `run.bat`, `VERSION`, `tools\launcher.ps1`, `requirements-runtime.txt`, 앱 소스, `사용방법.pdf`, `처음 읽어 주세요.txt`, 빈 `data` 폴더만 담습니다. 개인 데이터, 개발 환경, 테스트, 평가 정답셋은 넣지 않습니다. 앱 사이드바에 현재 버전이 표시됩니다. zip만 따로 만들려면 `scripts\build_dist.py <버전>`을 씁니다.

### 사용자 앱 업데이트 (GitHub Release)
사용자 앱의 **업데이트** 메뉴와 사이드바 알림은 `https://github.com/arching3/praycheck`의 최신 Release(`releases/latest`)를 봅니다. 저장소는 공개이며, 사용자 PC에는 git이나 로그인이 필요 없습니다.

공개 순서(관리자):
1. 변경을 커밋합니다. 배포 zip은 Stop 훅이 이미 만들어 둡니다.
2. `.venv\Scripts\python scripts\publish.py`를 실행합니다. 배포 zip을 사용자 앱과 같은 방식으로 검사(필수 파일, 버전, 개인 데이터 미포함)하고 `dist\praycheck_v<버전>.zip`과 `dist\release_notes_v<버전>.md`(SHA256 포함)를 만든 뒤 다음 단계를 출력합니다.
3. 릴리스 설명 파일의 "바뀐 점"을 쉬운 말로 채웁니다. 사용자가 업데이트 화면에서 그대로 읽습니다.
4. `git tag v<버전>` → `git push origin main` → `git push origin v<버전>`
5. GitHub의 **Releases → Draft a new release**에서 태그 선택 → 설명 붙여넣기 → `praycheck_v<버전>.zip` 첨부 → **Publish**(Pre-release 아님).

사용자 쪽 동작:
- 앱을 켤 때 새 버전이 있으면 사이드바에 알림과 **업데이트** 버튼이 표시됩니다. 확인은 6시간에 한 번입니다.
- **업데이트**를 누르면 zip을 받아 검증(크기, SHA256, 필수 파일, 버전)한 뒤 `update\staging`에 풀고 `update\ready.json`을 남깁니다. 그리고 "다시 실행해 주세요"를 띄웁니다.
- 다음 `run.bat` 실행 때 `launcher.ps1`이 `tools\apply_update.py`를 실행해 다음 순서로 적용합니다.
  1. DB를 `data\backup\prayer_tracker_업데이트전_v<버전>_<시각>.db`로 백업합니다. 최근 10개만 남깁니다.
  2. 바뀔 프로그램 파일을 `update\backup\v<이전 버전>\`에 백업합니다.
  3. 파일을 교체합니다. `VERSION`은 맨 마지막에 바꿉니다.
  4. `requirements-runtime.txt`가 바뀌었으면 구성 요소를 다시 설치합니다.
- 적용에 실패하면 백업에서 되돌리고 이전 버전으로 실행합니다. 결과는 `update\last_result.json`에 남고 업데이트 화면에 표시됩니다.
- `data\`, `runtime\`, `run.bat`은 바꾸지 않습니다. 개발 폴더(`.git`이 있는 곳)에서는 업데이트를 받지 않습니다.
- v1.0.0 사용자에게는 업데이트 기능이 없으므로 한 번만 수동으로 옮깁니다: `docs\기존 사용자 업데이트 안내.txt`.

## 판정 규칙 요약
- 메시지는 신뢰도 **HIGH**(명확한 규칙), **MEDIUM**(검증된 오타·구어체·문장 끝 인증, 정상 문맥에서 자동 확정), **LOW**(의미 불확실, 검토 대상)로 분류됩니다.
- 단독 "마칩니다"는 **진행 중인 세션이 있을 때만** 종료로 확정됩니다. 단독 "시작합니다"는 기본적으로 검토 대상입니다(설정으로 변경 가능).
- "다시 기도 시작합니다"는 재시작으로 보고 그 시점부터 새 세션을 만듭니다. 이모티콘 표기("(별똥별)")는 판정 전에 제거합니다. 해요체("기도 마쳤어요")도 인정합니다.
- 날짜 귀속은 04:00 기준 동적 귀속입니다. 새벽(04:00 이전) 시작은 전날 인증이 없으면 전날, 전날이 이미 완료면 당일로 귀속하고, 판단할 수 없으면 검토로 넘깁니다.
- 추적 시작일 이전으로 귀속될 새벽 인증은 집계하지 않습니다. 원본은 시작일 하루 전부터만 저장합니다.
- 수집 범위의 끝은 파일 머리의 "저장한 날짜"입니다. 하루의 상태는 다음 날 04:00까지의 데이터가 있어야 확정되므로, 마지막 날은 '데이터 확인 대기'로 보일 수 있습니다.
- 총 기도 시간은 시작·종료가 모두 확정된 세션만 합산하며, 미완료 세션의 시간은 추정하지 않습니다.
- 한 참여자·날짜는 항상 하나의 상태만 가집니다(완료 > 검토 대기 > 데이터 확인 대기 > 미완료 > 미인증).
- 관리자 수동 기록은 완료 세션으로 집계되고 새벽 귀속 판단에도 반영되며, CSV·PDF에 '수동'으로 표시됩니다.

## 데이터와 개인정보
- 모든 데이터는 로컬 SQLite 파일 `data/prayer_tracker.db`에만 저장되며 외부로 전송되지 않습니다.
- 실제 카카오톡 원본은 `private/`에 둡니다. `private/`, `data/`, `*.db`, 루트의 `*.txt`, 평가 정답셋은 `.gitignore`로 커밋을 막습니다.
- 업로드 페이지의 "모든 원본 데이터 삭제"로 메시지·판정·수동 기록을 지울 수 있습니다(참여자 설정은 유지).

## 주요 설계 결정
- **원본/판정 분리**: 원본 메시지는 변경하지 않고, 이벤트·세션·검토·일별 상태는 매번 원본에서 다시 계산한 파생 결과입니다.
- **재계산 결정성**: 같은 원본, 설정, 관리자 판정이면 업로드 순서와 관계없이 항상 같은 결과가 나옵니다.
- **관리자 판정 보존**: 관리자 지정(라벨, 연결, 날짜, 검토 상태, 수동 기록)은 별도 테이블에 저장되어 재계산·재업로드 후에도 유지되고 자동 분석이 덮어쓰지 않습니다. 모든 변경은 변경 이력에 기록됩니다.
- **중복 제거 키**: 발신자 + 분 단위 시각 + 본문 + 같은 분 안의 순번. 겹치는 기간의 파일을 다시 올려도 메시지가 중복되지 않습니다.

## 알려진 한계
- 카카오톡 TXT에는 서버 메시지 ID가 없어, 같은 분에 같은 발신자가 동일 본문을 여러 번 보낸 경우 파일 경계에서 중복/누락 판단이 어긋날 수 있습니다.
- 시각이 분 단위여서 기도 시간도 분 단위 정확도입니다.
- 실시간 수집은 없습니다. 파일을 내보내 다시 업로드해야 현황이 갱신됩니다.
- 퍼지(유사 문자열) 매칭은 짧은 문장에만 제한적으로 적용되며, 놓친 표현은 검토에서 직접 지정해야 합니다.
- 단일 관리자 전용입니다(동시 편집·권한 관리 없음).
