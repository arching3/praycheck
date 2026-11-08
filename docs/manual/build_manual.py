"""사용방법.pdf 생성: docs/manual/images의 화면 캡처로 HTML 설명서를 만들고 Edge로 PDF 인쇄한다.

필요: pip install playwright (브라우저는 설치된 Edge를 사용)
사용: python docs/manual/capture.py <작업 폴더>   # 화면 캡처(데모 데이터)
      python docs/manual/build_manual.py           # → docs/사용방법.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
IMAGES = HERE / "images"
BUILD = HERE / "build"
OUT = ROOT / "docs" / "사용방법.pdf"


def prepare_images() -> None:
    """캡처(1.5배율 PNG)를 인쇄용 JPEG로 줄여 PDF 용량을 낮춘다."""
    BUILD.mkdir(exist_ok=True)
    for src in IMAGES.glob("*.png"):
        im = Image.open(src).convert("RGB")
        if im.width > 1700:
            im = im.resize((1700, round(im.height * 1700 / im.width)), Image.LANCZOS)
        im.save(BUILD / f"{src.stem}.jpg", quality=88, optimize=True)


def fig(name: str, caption: str, width: str = "100%") -> str:
    # 세로로 긴 화면도 한 페이지 안에 들어가도록 높이를 제한한다
    return (f'<figure><img src="{name}.jpg" style="max-width:{width}"><figcaption>{caption}</figcaption></figure>')


CSS = """
@page { size: A4; margin: 18mm 16mm 20mm; }
* { box-sizing: border-box; }
body { font-family: 'Malgun Gothic', 'NanumGothic', sans-serif; color: #1f2328; font-size: 10.5pt; line-height: 1.65; }
h1 { font-size: 20pt; margin: 0 0 6mm; padding-bottom: 2mm; border-bottom: 2px solid #2e9d5b; break-before: page; }
h1.first { break-before: avoid; }
h2 { font-size: 13pt; margin: 7mm 0 2mm; color: #1f2328; }
h3 { font-size: 11pt; margin: 5mm 0 1.5mm; }
p { margin: 1.5mm 0 2.5mm; }
ul, ol { margin: 1mm 0 3mm; padding-left: 6mm; }
li { margin: 0.8mm 0; }
figure { margin: 3mm 0 5mm; break-inside: avoid; text-align: center; }
figure img { border: 1px solid #d0d7de; border-radius: 6px; max-height: 205mm; width: auto; height: auto; }
figcaption { font-size: 9pt; color: #6b7280; margin-top: 1.5mm; }
.note, .tip, .warn { border-radius: 6px; padding: 3mm 4mm; margin: 3mm 0; break-inside: avoid; }
.note { background: #eef6ff; border-left: 4px solid #3b7dd8; }
.tip { background: #edf7f0; border-left: 4px solid #2e9d5b; }
.warn { background: #fff6e5; border-left: 4px solid #e08a1e; }
table { border-collapse: collapse; width: 100%; margin: 2mm 0 4mm; font-size: 9.5pt; break-inside: avoid; }
th, td { border: 1px solid #d0d7de; padding: 1.6mm 2.4mm; text-align: left; vertical-align: top; }
th { background: #f3f5f8; }
code { font-family: Consolas, monospace; background: #f3f5f8; padding: 0 1.2mm; border-radius: 3px; font-size: 9.5pt; }
.pill { display: inline-block; padding: 0 2.5mm; border-radius: 10px; color: #fff; font-size: 9pt; font-weight: 700; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; }
.cover .bar { height: 4mm; background: #2e9d5b; width: 40mm; margin-bottom: 8mm; border-radius: 2px; }
.cover h1 { border: 0; font-size: 30pt; margin: 0; break-before: avoid; }
.cover .sub { font-size: 14pt; color: #6b7280; margin-top: 4mm; }
.cover .meta { margin-top: 30mm; color: #6b7280; font-size: 10pt; }
.toc { columns: 2; font-size: 11pt; }
.toc li { margin: 1.5mm 0; }
.steps li { margin: 2mm 0; }
"""


def body() -> str:
    g, o, r, y, gr = "#2e9d5b", "#e08a1e", "#d9534f", "#c9a227", "#8a8f98"
    pill = lambda c, t: f'<span class="pill" style="background:{c}">{t}</span>'  # noqa: E731
    return f"""
<section class="cover">
  <div class="bar"></div>
  <h1>기도 인증 현황</h1>
  <div class="sub">관리자 사용 설명서</div>
  <p style="margin-top:10mm;font-size:12pt">카카오톡 단톡방 대화를 올리면 대상자 10명의 매일 기도 시작·종료 인증을
  자동으로 찾아 기록하고, 확실하지 않은 것만 관리자에게 물어봅니다.</p>
  <div class="meta">2026년 10월 · Windows 로컬 앱(Streamlit)<br>
  이 설명서의 화면은 가상의 인물로 만든 데모 데이터입니다.</div>
</section>

<h1>목차</h1>
<ol class="toc">
  <li>한눈에 보기</li><li>설치와 실행</li><li>카카오톡 대화 내보내기</li><li>처음 설정: 추적 시작일과 업로드</li>
  <li>참여자 설정</li><li>대시보드</li><li>검토</li><li>수동 기록</li><li>개인별 현황</li><li>내보내기(CSV·Excel·PDF)</li>
  <li>설정</li><li>판정 규칙</li><li>매일 운영 순서</li><li>자주 묻는 질문</li>
</ol>

<h1>1. 한눈에 보기</h1>
<p>단톡방 참여자는 지금처럼 <b>"기도 시작합니다" / "기도 마칩니다"</b>를 올리기만 하면 됩니다. 관리자는 대화를 내보내 앱에 올리고,
앱이 정리한 결과를 확인합니다.</p>
<ul>
  <li><b>자동 판정</b>: 같은 사람의 시작·종료 메시지를 하나의 기도 세션으로 묶고, 기도 시간을 계산합니다.</li>
  <li><b>새벽 인증 처리</b>: 04:00 이전에 시작한 기도는 전날 인증 여부에 따라 전날 또는 당일로 자동 귀속합니다.</li>
  <li><b>검토</b>: "무튼 기도합니다"처럼 애매한 메시지는 임의로 인정하지 않고 관리자에게 물어봅니다.</li>
  <li><b>기록 보존</b>: 원본 대화는 바뀌지 않으며, 관리자의 모든 판정·수정은 변경 이력에 남습니다.</li>
  <li><b>개인정보</b>: 모든 데이터는 이 PC 안(<code>data\\prayer_tracker.db</code>)에만 저장되고 외부로 보내지지 않습니다.</li>
</ul>
<table>
  <tr><th>메뉴</th><th>하는 일</th></tr>
  <tr><td>대시보드</td><td>날짜별 10명 인증 현황, 월 달력, 타임라인</td></tr>
  <tr><td>개인별 현황</td><td>한 사람의 완료율·기도 시간·달력·세션 목록</td></tr>
  <tr><td>검토</td><td>자동으로 판정하지 못한 메시지를 관리자가 결정</td></tr>
  <tr><td>수동 기록</td><td>카톡 인증 없이 확인된 기도를 직접 추가·수정·삭제</td></tr>
  <tr><td>메시지/판정</td><td>참여자의 모든 메시지와 판정 결과 조회, 직접 지정</td></tr>
  <tr><td>업로드</td><td>카카오톡 대화 파일 올리기, 데이터 위치·삭제</td></tr>
  <tr><td>참여자 설정</td><td>인증 대상자 10명 지정, 이름 변경, 닉네임 병합</td></tr>
  <tr><td>설정</td><td>추적 시작일, 자동 판정 규칙</td></tr>
  <tr><td>내보내기</td><td>CSV·Excel, 하루 1페이지 PDF 보고서, PNG 이미지</td></tr>
  <tr><td>변경 이력</td><td>업로드·판정·수정·삭제 기록</td></tr>
  <tr><td>업데이트</td><td>새 버전 확인, 내려받아 준비(다시 실행하면 적용)</td></tr>
</table>

<h1>2. 설치와 실행</h1>
<p>따로 설치할 프로그램은 없습니다. 받은 압축 파일을 풀고 <code>run.bat</code>을 더블클릭하면 됩니다.
필요 환경은 <b>Windows 10/11(64비트)</b>이며, 처음 실행할 때만 인터넷 연결이 필요합니다.</p>
<h2>처음 한 번</h2>
<ol class="steps">
  <li>압축 파일을 바탕 화면 등 원하는 곳에 <b>압축 풀기</b> 합니다(압축 파일 안에서 바로 실행하지 마세요).</li>
  <li>압축을 푼 폴더의 <code>run.bat</code>을 더블클릭합니다.</li>
  <li>"Windows의 PC 보호" 파란 창이 뜨면 <b>추가 정보 → 실행</b>을 누릅니다.</li>
  <li>검은 창에 준비 과정이 표시됩니다(3~10분). 프로그램 폴더 안에 필요한 파일을 내려받는 것으로, PC 설정은 바뀌지 않습니다.</li>
  <li>준비가 끝나면 브라우저에 프로그램 화면이 자동으로 열립니다.</li>
</ol>
<h2>매번 실행</h2>
<ol class="steps">
  <li><code>run.bat</code>을 더블클릭하면 몇 초 뒤 브라우저에 앱이 열립니다.</li>
  <li>브라우저가 열리지 않으면 검은 창에 표시된 주소(예: <code>http://localhost:8501</code>)를 주소창에 입력합니다.</li>
  <li>사용을 마치면 브라우저 탭과 검은 창을 닫습니다. 기록은 자동 저장되어 다음 실행 때 그대로 남아 있습니다.</li>
</ol>
<div class="note">검은 창을 닫으면 앱이 멈춥니다. 앱을 쓰는 동안에는 창을 최소화만 해 두세요.</div>
<div class="tip"><b>문제가 생기면</b> 인터넷 연결을 확인하고 다시 실행하세요. 그래도 안 되면 프로그램 폴더의 <code>runtime</code> 폴더를
지우고 다시 실행하면 준비 과정을 처음부터 다시 합니다(기록은 지워지지 않습니다). 폴더 경로가 너무 길면 실패할 수 있으니
바탕 화면이나 <code>C:\\</code> 바로 아래에 두세요.</div>
<h2>새 버전으로 업데이트</h2>
<p>새 버전이 나오면 앱 왼쪽 메뉴 위에 <b>"새 버전이 있습니다"</b> 알림과 <b>업데이트</b> 버튼이 보입니다.
왼쪽 메뉴의 <b>업데이트</b>에서 직접 확인할 수도 있습니다.</p>
<ol class="steps">
  <li><b>업데이트</b> 버튼을 누르면 바뀐 내용을 보여 주고, 새 버전을 내려받아 준비합니다.</li>
  <li>"업데이트 준비를 마쳤습니다"가 나오면 브라우저 탭과 <b>검은 창을 닫고</b> <code>run.bat</code>을 다시 실행합니다.</li>
  <li>다시 실행할 때 검은 창에 "새 버전을 적용합니다"가 표시되고, 끝나면 평소처럼 앱이 열립니다.</li>
</ol>
<div class="note">업데이트는 <b>프로그램 파일만</b> 바꿉니다. 기록(<code>data</code> 폴더)은 그대로 두고, 적용 직전에
<code>data\\backup</code> 폴더에 기록 사본을 하나 더 만들어 둡니다. 적용 중 문제가 생기면 원래 파일로 되돌리고 이전 버전으로 실행합니다.</div>

<h1>3. 카카오톡 대화 내보내기</h1>
<ol class="steps">
  <li>PC 카카오톡에서 기도 인증 단톡방을 엽니다.</li>
  <li>오른쪽 위 메뉴(≡) → 설정 → <b>대화 내용 내보내기</b> → <b>텍스트만 보내기</b>를 선택해 <code>.txt</code> 파일로 저장합니다.</li>
  <li>저장된 파일을 앱의 <b>업로드</b> 메뉴에 그대로 올립니다.</li>
</ol>
<div class="tip"><b>항상 전체 파일을 그대로 올리세요.</b> 카카오톡은 기간을 골라 내보낼 수 없으므로 매번 전체 대화가 담깁니다.
앱이 이미 반영된 메시지는 자동으로 건너뛰고 새 메시지만 추가하므로, 같은 기간이 겹쳐도 기록이 중복되지 않습니다.</div>
<div class="warn">날짜별로 나눈 파일(분할 스크립트 결과)은 업로드하지 마세요. 날짜 사이의 수집 범위가 끊겨 새벽 인증의
날짜를 판단하지 못합니다.</div>

<h1>4. 처음 설정: 추적 시작일과 업로드</h1>
<p>처음에는 <b>추적 시작일</b>(인증 집계를 시작할 날짜)을 정해야 업로드할 수 있습니다.
원본 대화는 개인정보 보호를 위해 <b>시작일 하루 전부터만</b> 저장되고, 그 이전 대화는 읽기만 하고 버립니다.</p>
{fig("01_upload_need_start", "업로드 화면 — 추적 시작일을 정하기 전에는 파일을 올릴 수 없습니다.")}
<ol class="steps">
  <li>추적 시작일을 고르고 <b>시작일 저장</b>을 누릅니다.</li>
  <li>파일 상자에 내보낸 <code>.txt</code> 파일을 끌어다 놓고 <b>가져오기</b>를 누릅니다.</li>
  <li>결과에 전체 메시지 수, 새로 저장된 수, 시작일 이전이라 건너뛴 수, 내보내기 시각이 표시됩니다.</li>
</ol>
{fig("02_upload_done", "업로드 결과 — 처음 보는 닉네임은 '새 참여자'로 안내됩니다.")}
<div class="note">시작일은 나중에 <b>설정</b>에서 바꿀 수 있습니다. 시작일을 <b>앞당겼다면</b> 같은 전체 파일을 다시 올리면
모자란 앞부분만 채워집니다. <b>늦췄다면</b> 설정 화면의 "범위 이전 원본 삭제"로 필요 없는 원본을 지울 수 있습니다.</div>

<h1>5. 참여자 설정</h1>
<p>업로드하면 대화에 등장한 모든 닉네임이 참여자로 등록되지만, <b>인증 대상자는 자동으로 정해지지 않습니다.</b>
대상자 10명을 직접 체크하고 <b>대상자 저장</b>을 누르세요. 대상이 아닌 사람은 집계에서 빠집니다.</p>
{fig("03_members", "참여자 설정 — '대상' 열을 체크해 인증 대상자를 정합니다.")}
<ul>
  <li><b>이름 변경</b>: 보고서에 표시할 이름을 바꿉니다.</li>
  <li><b>참여자 병합</b>: 누군가 카카오톡 닉네임을 바꾸면 새 닉네임이 다른 사람처럼 등록됩니다. "병합할 참여자(A)"에 새 닉네임,
  "합칠 대상(B)"에 기존 사람을 고르고 <b>병합</b>을 누르면 두 닉네임의 기록이 한 사람으로 합쳐집니다.</li>
</ul>

<h1>6. 대시보드</h1>
<p>날짜를 골라 대상자 전체의 인증 현황을 봅니다.</p>
{fig("04_dashboard", "대시보드 — 월 달력, 요약 숫자, 타임라인, 현황표")}
<h3>월 달력</h3>
<p>날짜 버튼을 누르면 그 날짜의 현황이 아래에 표시됩니다. ◀ ▶로 달을 이동하고, <b>최근</b>은 가장 최근 날짜로 갑니다.
버튼의 <code>9/10</code>은 "대상 10명 중 9명 완료"라는 뜻입니다.</p>
<table>
  <tr><th>표시</th><th>뜻</th></tr>
  <tr><td>🟢</td><td>대상자 전원 완료</td></tr>
  <tr><td>🔴</td><td>미완료 또는 미인증인 사람이 있음</td></tr>
  <tr><td>🟠</td><td>관리자 검토가 필요한 사람이 있음</td></tr>
  <tr><td>⚪</td><td>아직 데이터가 다 모이지 않음(마지막 날 등)</td></tr>
</table>
<h3>타임라인</h3>
<p>한 사람당 한 줄로, 기도한 시간대를 막대로 보여줍니다. 막대에 마우스를 올리면 시작·종료·기도 시간이 보입니다.
다음 날 새벽에 기도했지만 이 날짜로 귀속된 경우도 함께 표시되며, 자정과 04:00 귀속 경계는 점선으로 그려집니다.</p>
<h3>현황표</h3>
<p>사람별 인증 상태, 시작·종료 시각, 기도 시간, 실제 시작 날짜와 귀속 날짜, 귀속 방식, 검토 필요 여부가 나옵니다.
표 아래 이름 버튼을 누르면 그 사람의 <b>개인별 현황</b>으로 이동합니다.</p>

<h1>7. 검토</h1>
<p>앱이 확실하게 판정하지 못한 경우에만 검토 항목이 생깁니다. 사이드바의 <b>검토 (2)</b>처럼 남은 건수가 표시됩니다.
검토가 끝나지 않은 날은 "미인증"으로 확정되지 않고 <b>검토 대기</b>로 남습니다.</p>
{fig("05_review", "검토 화면 — 사유와 후보 메시지, 처리 버튼")}
<h3>검토가 생기는 경우</h3>
<ul>
  <li><b>시작 누락</b>: 종료 메시지는 있는데 시작이 확인되지 않음(예: "무튼 기도합니다"처럼 애매한 시작)</li>
  <li><b>종료 누락</b>: 시작은 있는데 종료 후보가 애매함</li>
  <li><b>시작/종료 중복</b>, <b>의미 불확실</b>, <b>날짜 귀속</b>(전날 기록이 불완전해 날짜를 정할 수 없음)</li>
</ul>
<h3>처리 방법</h3>
<table>
  <tr><th>버튼</th><th>언제 쓰나</th></tr>
  <tr><td><b>START / END / OTHER</b></td><td>메시지를 시작 / 종료 / 인증 아님으로 지정. 지정된 버튼은 <b>✓</b>로 바뀌며, 다시 누르면 지정이 해제됩니다.</td></tr>
  <tr><td><b>선택한 두 메시지 연결</b></td><td>"연결 선택"으로 두 메시지를 고르고 누르면 하나의 세션으로 묶습니다.</td></tr>
  <tr><td><b>올바른 후보 없음</b></td><td>후보가 모두 인증이 아닐 때. 검토 목록에서 빠집니다.</td></tr>
  <tr><td><b>보류</b></td><td>나중에 결정. "보류 항목도 보기"를 켜면 다시 볼 수 있습니다.</td></tr>
  <tr><td><b>이 날짜로 귀속</b></td><td>날짜 귀속 검토에서 인증 날짜를 직접 정합니다.</td></tr>
  <tr><td><b>앞뒤 대화 보기</b></td><td>후보에 정답이 없을 때 주변 대화를 펼쳐 다른 메시지를 직접 지정합니다.</td></tr>
</table>
<p>처리하면 그 항목이 사라지지 않고 같은 자리에 <b>"✅ 처리 완료"</b> 카드로 남아, 만들어진 세션과 그날 상태를 보여줍니다.
잘못 눌렀다면 카드의 <b>↩ 되돌리기</b>를 누르세요. 화면 구석에는 처리 결과 알림이 잠깐 뜹니다.</p>
{fig("06_review_done", "START로 지정한 뒤 — 초록색으로 표시되고 30분 세션이 만들어졌습니다.")}
<div class="tip">관리자가 지정한 판정은 파일을 다시 올리거나 다시 계산해도 <b>자동 판정이 덮어쓰지 않습니다.</b></div>

<h1>8. 수동 기록</h1>
<p>카톡에 인증을 올리지 못했지만 기도한 것이 확인된 경우(전화로 확인, 종료 인증 누락 등) 관리자가 기록을 직접 넣습니다.
수동 기록은 <b>완료</b>로 집계되고, 원본 대화는 바뀌지 않습니다.</p>
{fig("08_manual", "수동 기록 — 추가 후 알림과 목록. 목록에서 수정·삭제할 수 있습니다.")}
<ul>
  <li><b>추가</b>: 참여자, 인증 날짜, 시작·종료 시각, 메모를 입력하고 <b>추가</b>. 아래에 실제 시각이 미리 계산되어 보입니다.</li>
  <li><b>시각 해석</b>: 04:00 이전 시작은 인증 날짜의 <b>다음 날 새벽</b>으로 봅니다(예: 10/28 기록에 01:10 → 10/29 01:10).
  종료가 시작보다 이르면 자정을 넘긴 것으로 봅니다(23:40 → 00:20은 40분).</li>
  <li><b>수정</b>: 목록의 <b>수정</b>을 누르면 위 입력란에 값이 채워집니다. 고친 뒤 <b>수정 저장</b>.</li>
  <li><b>삭제</b>: <b>삭제</b> → 한 번 더 확인. 삭제 직후 "↩ 방금 삭제한 기록 되돌리기"로 복구할 수 있습니다.</li>
  <li>개인별 현황에서 날짜를 고른 뒤 <b>＋ 수동 기록 추가</b>를 누르면 참여자와 날짜가 채워진 채로 이 화면이 열립니다.</li>
</ul>
<div class="note">수동 기록은 CSV에 "입력 방식: 수동 기록", PDF 보고서에 "· 수동"으로 표시되어 자동 인증과 구분됩니다.
추가·수정·삭제는 모두 변경 이력에 남습니다.</div>

<h1>9. 개인별 현황</h1>
<p>위쪽 이름 버튼으로 사람을 고릅니다. 대시보드나 검토 화면에서 이름을 눌러도 이 화면으로 옵니다.</p>
{fig("07_person", "개인별 현황 — 요약 지표, 개인 달력, 세션 목록", "92%")}
<ul>
  <li><b>완료율</b> = 완료한 날 ÷ 판정이 끝난 날. 검토 대기·데이터 확인 대기인 날은 빼고 계산합니다.</li>
  <li><b>개인 달력</b>: 날짜마다 상태와 기도 시간(예: <code>12 · 34분</code>)을 보여줍니다. 날짜를 누르면 그날 세션이 아래에 나옵니다.</li>
  <li><b>탭</b>: 세션 목록(CSV 받기), 미인증·미완료 날짜, 이 사람의 검토 항목(바로 처리 가능)</li>
</ul>

<h1>10. 내보내기</h1>
<p>기간을 고른 뒤 원하는 형식으로 받습니다.</p>
<ul>
  <li><b>CSV / Excel</b>: 날짜별 현황표, 세션 상세 내역(두 시트)</li>
  <li><b>PDF 보고서</b>: 하루 1페이지. <b>PDF 만들기</b> → <b>PDF 받기</b></li>
  <li><b>PNG 이미지</b>: 슬라이더로 고른 하루를 이미지로 받아 단톡방에 바로 공유할 수 있습니다.</li>
</ul>
{fig("09_export", "내보내기 — CSV/Excel 버튼, PDF 보고서와 미리보기", "92%")}
{fig("11_pdf_page", "PDF 보고서 한 페이지 — 이름 · 인증 여부 · 세션 시작 · 종료 · 지속 시간", "62%")}
<p>PDF에서 "익일 02:01"은 다음 날 새벽 시각, "종료 없음"은 종료 인증이 없는 세션입니다(기도 시간을 추정하지 않습니다).</p>

<h1>11. 설정</h1>
{fig("10_settings", "설정 — 추적 시작일과 판정 규칙", "92%")}
<table>
  <tr><th>항목</th><th>설명</th><th>기본값</th></tr>
  <tr><td>추적 시작일</td><td>이 날짜부터 집계. 원본은 하루 전부터만 저장</td><td>처음에 직접 지정</td></tr>
  <tr><td>새벽 유예 시각</td><td>이 시각 이전에 시작한 기도는 전날 귀속 규칙 적용</td><td>4시</td></tr>
  <tr><td>세션 최대 길이</td><td>시작~종료가 이보다 길면 자동 연결하지 않음</td><td>6시간</td></tr>
  <tr><td>단독 '마칩니다' 자동 확정</td><td>기도가 진행 중일 때만 "마칩니다"만 올려도 종료로 인정</td><td>켜짐</td></tr>
  <tr><td>단독 '시작합니다' 자동 확정</td><td>"시작합니다"만 올린 경우 자동 인정 여부</td><td>꺼짐(검토)</td></tr>
  <tr><td>단독 '기도합니다' 자동 확정</td><td>"기도합니다" 뒤에 같은 사람의 종료("기도 마칩니다", "마칩니다")가 6시간 안에 오면 시작으로 인정. 종료가 없으면 검토</td><td>켜짐</td></tr>
  <tr><td>오타·구어체 자동 확정</td><td>"기도시작합니당", "ㄱ도 마칩니다" 등을 정상 흐름에서 인정</td><td>켜짐</td></tr>
  <tr><td>문장 끝 인증 자동 확정</td><td>"…가지고 기도 시작합니다"를 정상 흐름에서 인정</td><td>켜짐</td></tr>
  <tr><td>퍼지 매칭 유사도</td><td>오타 후보를 찾는 기준(높을수록 엄격). 찾은 후보는 검토로 보냄</td><td>85</td></tr>
</table>

<h1>12. 판정 규칙</h1>
<h2>인증으로 인정되는 표현</h2>
<table>
  <tr><th>구분</th><th>예시</th><th>처리</th></tr>
  <tr><td>명확한 시작/종료</td><td>기도 시작합니다 · 기도시작합니다 · 기도하겠습니다 · 기도 시작~ · 기도 마칩니다 · 기도 마쳤습니다 · 기도 마쳤어요 ·
  기도 마쳤습니다!(별똥별)</td><td>자동 인정</td></tr>
  <tr><td>오타·구어체</td><td>기도시작합니당 · 기도 마칩니당 · ㄱ도 마칩니다 · 마쳤습니다아 · 기도 마쳤어용 · 기도 끝했어요</td><td>흐름이 맞으면 자동 인정</td></tr>
  <tr><td>단독 종료</td><td>마칩니다 · 마쳤습니다 · 마쳤어요</td><td>그 사람이 기도 중일 때만 인정</td></tr>
  <tr><td>단독 "기도합니다"</td><td>기도합니다 · 기도 합니다!</td><td>같은 사람의 종료가 뒤따르면 시작으로 인정, 아니면 검토</td></tr>
  <tr><td>문장 끝 인증</td><td>감사한 마음을 가지고 기도 시작합니다!</td><td>흐름이 맞으면 자동 인정</td></tr>
  <tr><td>재시작</td><td>다시 기도 시작합니다</td><td>앞선 시작은 중단으로 보고, 다시 시작한 시점부터 새 세션</td></tr>
  <tr><td>애매한 표현</td><td>무튼 기도합니다 · 시작합니다 · 기도 시작합니더</td><td>검토로 보냄</td></tr>
</table>
<h2>인증으로 보지 않는 표현</h2>
<p>오늘 기도회 누구니? · 기도해주셔서 감사합니다 · 기도 부탁드립니다 · 기도할게요 진짜루, 파이팅 ·
기도 시작-마침 안 올리는 사람 체크해줘 · 원투원 마쳤습니다 · 사진 · 이모티콘 · 삭제된 메시지</p>
<h2>새벽 인증의 날짜(04:00 규칙)</h2>
<p>00:00~04:00 사이에 <b>시작한</b> 기도는 전날 인증이 있으면 당일, 없으면 전날로 귀속합니다. 종료 시각이 아니라 시작 시각을 기준으로 합니다.</p>
<table>
  <tr><th>시작</th><th>종료</th><th>전날(화) 상태</th><th>귀속</th></tr>
  <tr><td>수 03:00</td><td>수 03:30</td><td>미인증</td><td>화요일</td></tr>
  <tr><td>수 03:00</td><td>수 03:30</td><td>완료</td><td>수요일</td></tr>
  <tr><td>화 23:40</td><td>수 00:20</td><td>—</td><td>화요일(자정을 넘겨도 나누지 않음)</td></tr>
  <tr><td>수 03:59</td><td>수 04:30</td><td>미인증</td><td>화요일</td></tr>
  <tr><td>수 04:00</td><td>수 04:30</td><td>미인증</td><td>수요일</td></tr>
  <tr><td>수 03:00</td><td>수 03:30</td><td>시작만 있음</td><td>검토</td></tr>
</table>
<h2>하루 상태</h2>
<table>
  <tr><th>상태</th><th>뜻</th></tr>
  <tr><td>{pill(g, "완료")}</td><td>그날로 귀속된 완료 세션(시작+종료)이 하나 이상 있음</td></tr>
  <tr><td>{pill(o, "미완료")}</td><td>시작 또는 종료가 빠진 세션만 있음</td></tr>
  <tr><td>{pill(r, "미인증")}</td><td>데이터는 충분한데 인증이 없음</td></tr>
  <tr><td>{pill(y, "검토 대기")}</td><td>관리자 결정이 필요한 항목이 있음(미인증으로 단정하지 않음)</td></tr>
  <tr><td>{pill(gr, "데이터 확인 대기")}</td><td>그날 인증 가능 시간(다음 날 04:00까지)의 대화가 아직 다 모이지 않음</td></tr>
</table>

<h1>13. 매일 운영 순서</h1>
<ol class="steps">
  <li>PC 카카오톡에서 단톡방 대화를 <b>전체 내보내기</b>(텍스트)</li>
  <li>앱의 <b>업로드</b>에 그대로 올리고 <b>가져오기</b></li>
  <li>사이드바 <b>검토 (N)</b>이 0이 될 때까지 처리</li>
  <li><b>대시보드</b>에서 어제 날짜를 눌러 🟢인지 확인, 🔴이면 현황표에서 누가 미완료·미인증인지 확인</li>
  <li>확인된 누락이 있으면 <b>수동 기록</b>으로 보완</li>
  <li>필요하면 <b>내보내기</b>에서 PDF·PNG로 공유</li>
</ol>
<div class="tip">오늘 날짜는 다음 날 04:00까지의 대화가 모여야 확정되므로, 하루 상태 확인은 <b>다음 날 아침 이후</b>에 하는 것이 정확합니다.</div>

<h1>14. 자주 묻는 질문</h1>
<h3>같은 파일을 두 번 올리면 기록이 두 배가 되나요?</h3>
<p>아니요. 완전히 같은 파일은 "이미 업로드된 파일"로 막히고, 기간이 겹치는 새 파일은 새 메시지만 추가됩니다.</p>
<h3>마지막 날이 "데이터 확인 대기"로 나옵니다.</h3>
<p>정상입니다. 그날의 인증은 다음 날 04:00까지 올라올 수 있으므로, 그 시각 이후에 내보낸 파일을 올리면 확정됩니다.</p>
<h3>잘못 판정한 것을 되돌리고 싶어요.</h3>
<p>검토 화면의 <b>↩ 되돌리기</b>, 또는 같은 버튼(✓ START 등)을 다시 눌러 지정을 해제합니다. 지난 판정은
<b>메시지/판정</b> 메뉴에서 메시지를 골라 다시 지정하거나 "지정 해제"할 수 있습니다.</p>
<h3>누가 언제 무엇을 바꿨는지 볼 수 있나요?</h3>
<p><b>변경 이력</b> 메뉴에 업로드, 대상자 지정, 판정, 수동 기록 추가·수정·삭제가 바뀌기 전후 값과 함께 남습니다.</p>
<h3>데이터는 어디에 있고, 지우려면?</h3>
<p>프로그램 폴더의 <code>data\\prayer_tracker.db</code> 한 파일입니다. <code>data</code> 폴더를 복사해 두면 백업이 되고,
앱의 <b>업데이트</b>로 새 버전을 받으면 기록은 그대로 이어집니다(적용 직전 <code>data\\backup</code>에 사본이 자동 저장됩니다).
<b>업로드</b> 메뉴 아래 "모든 원본 데이터 삭제"로 대화·판정·수동 기록을 지울 수 있습니다(참여자 설정은 유지).</p>
<h3>닉네임이 바뀐 사람이 두 명으로 보여요.</h3>
<p><b>참여자 설정 → 참여자 병합</b>에서 새 닉네임을 기존 사람에게 합치세요.</p>
"""


def build() -> None:
    prepare_images()
    html = f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>기도 인증 현황 사용 설명서</title>" \
           f"<style>{CSS}</style></head><body>{body()}</body></html>"
    page_file = BUILD / "manual.html"
    page_file.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        page.goto(page_file.as_uri())
        page.wait_for_load_state("networkidle")
        page.pdf(path=str(OUT), format="A4", print_background=True, display_header_footer=True,
                 header_template="<div></div>",
                 footer_template="<div style='width:100%;font-size:8px;color:#888;text-align:center;"
                                 "font-family:Malgun Gothic'>기도 인증 현황 사용 설명서 · "
                                 "<span class='pageNumber'></span> / <span class='totalPages'></span></div>",
                 margin={"top": "18mm", "bottom": "20mm", "left": "16mm", "right": "16mm"})
        browser.close()
    print(OUT)


if __name__ == "__main__":
    build()
    sys.exit(0)
