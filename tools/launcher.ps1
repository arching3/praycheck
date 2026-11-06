# 기도 인증 현황 실행기 (run.bat이 호출)
# 처음 실행: 이 폴더의 runtime\ 안에 휴대용 Python과 구성 요소를 설치한다(관리자 권한·PC 설정 변경 없음).
# 이후 실행: 앱 서버를 띄우고 준비되면 브라우저를 연다. 이 창을 닫으면 앱이 종료된다.

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$Host.UI.RawUI.WindowTitle = '기도 인증 현황'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'   # 내려받기 속도 저하 방지

$PyVersion = '3.13.14'
$Root      = Split-Path -Parent $PSScriptRoot
# 구성 요소 안에 아주 깊은 폴더(약 140자)가 있어, 프로그램 폴더 경로가 길면 Windows 경로 길이 제한(260자)에 걸린다.
# 경로가 짧으면 프로그램 폴더 안에, 길면 사용자 폴더(LOCALAPPDATA, 관리자 권한 불필요)에 설치한다. 기록(data)은 항상 프로그램 폴더.
$Runtime   = Join-Path $Root 'runtime'
if ($Runtime.Length -gt 80) {
    $tag = ((Get-FileHash -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($Root.ToLower())))).Hash).Substring(0, 8)
    $Runtime = Join-Path $env:LOCALAPPDATA "PrayerTracker\rt-$tag"
}
$PyDir     = Join-Path $Runtime 'python'
$Py        = Join-Path $PyDir 'python.exe'
$Req       = Join-Path $Root 'requirements-runtime.txt'
$Marker    = Join-Path $Runtime 'ready.txt'
$Log       = Join-Path $Runtime 'setup.log'
$App       = Join-Path $Root 'prayer_tracker\ui\app.py'

function Say([string]$msg, [string]$color = 'Gray') { Write-Host $msg -ForegroundColor $color }

function Fail([string]$msg, [string]$detailFile = $Log) {
    Say ''
    Say "[문제가 생겼습니다] $msg" Red
    if (Test-Path $detailFile) {
        Say '--- 자세한 내용(마지막 부분) ---' DarkGray
        Get-Content $detailFile -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Say $_ DarkGray }
    }
    Say ''
    Say '해결 방법:' Yellow
    Say ' 1) 인터넷이 연결되어 있는지 확인한 뒤 run.bat을 다시 실행해 보세요.' Yellow
    Say " 2) 그래도 안 되면 아래 폴더를 지우고 다시 실행해 보세요. (기록은 지워지지 않습니다)`n    $Runtime" Yellow
    Say ' 3) 폴더 경로가 너무 길면 실패할 수 있습니다. 바탕 화면이나 C:\ 바로 아래로 옮겨 보세요.' Yellow
    Say ''
    Read-Host 'Enter 키를 누르면 창이 닫힙니다' | Out-Null
    exit 1
}

# 오래 걸리는 작업은 점(.)을 찍으며 기다린다. 출력은 로그 파일로.
function Run-Step([string]$label, [string]$argLine) {
    Say "  $label" White
    $out = Join-Path $Runtime 'step.out.log'
    $err = Join-Path $Runtime 'step.err.log'
    $p = Start-Process -FilePath $Py -ArgumentList $argLine -WorkingDirectory $Root -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle   # PowerShell 5.1: 핸들을 잡아 두지 않으면 종료 후 ExitCode가 비어 있다
    $n = 0
    while (-not $p.HasExited) {
        Start-Sleep -Seconds 2
        $n++
        Write-Host -NoNewline '.'
        if ($n % 30 -eq 0) { Write-Host " ($([int]($n * 2 / 60))분 경과)" }
    }
    Write-Host ''
    $p.WaitForExit()
    foreach ($f in @($out, $err)) {
        if (Test-Path $f) { Get-Content $f -ErrorAction SilentlyContinue | Add-Content $Log; Remove-Item $f -ErrorAction SilentlyContinue }
    }
    if ($p.ExitCode -ne 0) { throw "$label 실패 (코드 $($p.ExitCode))" }
}

function Setup {
    Say ''
    Say '처음 실행을 준비합니다. (한 번만 하면 됩니다)' Cyan
    Say ' - 인터넷 연결이 필요하고, 3~10분 정도 걸립니다.' Cyan
    Say " - 설치 위치: $Runtime" Cyan
    Say ' - 관리자 권한이 필요 없고, PC 설정은 바뀌지 않습니다.' Cyan
    Say ''
    New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
    "=== 준비 시작 $(Get-Date -Format s) ===" | Add-Content $Log
    if (-not (Test-Path $Py)) {
        Say '[1/3] Python 내려받는 중...' White
        $zip = Join-Path $Runtime 'python.zip'
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip" `
            -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $PyDir -Force
        Remove-Item $zip
        # 휴대용 Python이 설치 도구(site-packages)를 쓰도록 설정
        $pth = Get-ChildItem -Path $PyDir -Filter 'python*._pth' | Select-Object -First 1
        (Get-Content $pth.FullName) -replace '^#\s*import site', 'import site' | Set-Content $pth.FullName -Encoding ASCII
    }
    if (-not (Test-Path (Join-Path $PyDir 'Lib\site-packages\pip'))) {
        Say '[2/3] 설치 도구 준비 중...' White
        $gp = Join-Path $Runtime 'get-pip.py'
        Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $gp -UseBasicParsing
        Run-Step '설치 도구 설치' "`"$gp`" --no-warn-script-location --disable-pip-version-check"
        Remove-Item $gp -ErrorAction SilentlyContinue
    }
    Say '[3/3] 프로그램 구성 요소 설치 중... (가장 오래 걸립니다)' White
    Run-Step '구성 요소 설치' "-m pip install --no-compile --no-warn-script-location --disable-pip-version-check -r `"$Req`""
    Set-Content -Path $Marker -Value $script:ReqHash
    Say '준비가 끝났습니다!' Green
}

function Free-Port {
    foreach ($port in 8501..8530) {
        $l = $null
        try {
            $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port)
            $l.Start(); $l.Stop()
            return $port
        } catch { if ($l) { $l.Stop() } }
    }
    throw '사용할 수 있는 포트를 찾지 못했습니다.'
}

# ---------------------------------------------------------------- 준비
Say '=== 기도 인증 현황 ===' Green
$script:ReqHash = (Get-FileHash -Path $Req -Algorithm SHA256).Hash
$ready = (Test-Path $Py) -and (Test-Path $Marker) -and ((Get-Content $Marker -Raw).Trim() -eq $script:ReqHash)
if (-not $ready) {
    try { Setup } catch { $_ | Out-String | Add-Content $Log; Fail "처음 실행 준비에 실패했습니다. ($($_.Exception.Message))" }
}

# ---------------------------------------------------------------- 업데이트 적용
# 앱의 [업데이트] 화면에서 준비해 둔 새 버전이 있으면, 서버를 띄우기 전에 프로그램 파일만 바꾼다.
# 기록(data)은 바꾸지 않고, 적용 전에 data\backup에 사본을 만든다. 실패하면 원래 파일로 되돌리고 이전 버전으로 실행한다.
$Ready = Join-Path $Root 'update\ready.json'
$Applier = Join-Path $Root 'tools\apply_update.py'
if ((Test-Path $Ready) -and (Test-Path $Applier)) {
    Say ''
    Say '준비된 새 버전을 적용합니다...' Cyan
    $env:PYTHONIOENCODING = 'utf-8'
    & $Py $Applier $Root
    if ($LASTEXITCODE -ne 0) {
        Say '업데이트를 적용하지 못했습니다. 이전 버전으로 실행합니다. (기록은 그대로입니다)' Yellow
        Start-Sleep -Seconds 3
    } else {
        # 새 버전의 구성 요소 목록이 바뀌었으면 다시 설치한다
        $script:ReqHash = (Get-FileHash -Path $Req -Algorithm SHA256).Hash
        if ((Get-Content $Marker -Raw).Trim() -ne $script:ReqHash) {
            try { Setup } catch { $_ | Out-String | Add-Content $Log; Fail "새 버전 구성 요소 설치에 실패했습니다. ($($_.Exception.Message))" }
        }
    }
}

# ---------------------------------------------------------------- 실행
try { $port = Free-Port } catch { Fail $_.Exception.Message }
# "localhost"는 IPv6(::1)를 먼저 시도해 Windows에서 약 2초씩 지연된다 → IPv4 주소를 직접 쓴다
$url = "http://127.0.0.1:$port"
$srvOut = Join-Path $Runtime 'server.out.log'
$srvErr = Join-Path $Runtime 'server.err.log'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = 'false'
Say ''
Say '프로그램을 시작하는 중...' White
$server = Start-Process -FilePath $Py -WorkingDirectory $Root -NoNewWindow -PassThru `
    -RedirectStandardOutput $srvOut -RedirectStandardError $srvErr `
    -ArgumentList "-m streamlit run `"$App`" --server.headless true --server.port $port --server.address 127.0.0.1 --theme.base light --global.developmentMode false"

$ok = $false
for ($i = 0; $i -lt 90; $i++) {
    if ($server.HasExited) { break }
    try {
        $r = Invoke-WebRequest -Uri "$url/_stcore/health" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $ok) {
    if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
    Fail '프로그램이 시작되지 않았습니다.' $srvErr
}

try { Start-Process $url } catch { Say "브라우저를 자동으로 열지 못했습니다. 아래 주소를 브라우저 주소창에 직접 입력해 주세요." Yellow }
Say ''
Say '프로그램이 실행 중입니다.' Green
Say "  브라우저가 열리지 않으면 주소창에 입력하세요:  $url" White
Say ''
Say '  ※ 이 검은 창을 닫으면 프로그램이 종료됩니다. 사용하는 동안에는 최소화만 해 두세요.' Yellow
Say '  ※ 기록은 자동으로 저장됩니다 (data 폴더).' Yellow
$server.WaitForExit()
