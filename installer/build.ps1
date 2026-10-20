# Builds installer\build\Hivemind-Setup.exe on Windows (RL6i).
# The GitHub workflow runs exactly this; installer\README.md says how to run
# it by hand. Needs: any Python 3.9+ with pip (only to fetch the wheels; they
# are chosen for 3.12 win_amd64 whatever runs pip), 7-Zip, and Inno Setup 6
# (installed with choco when missing).
#
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1
#
# The app folder it makes is the repo's own layout, so the code runs exactly as
# it does from a checkout (installer\README.md, "Why embedded Python"):
#   python\      the official embeddable CPython + the pinned wheels
#   src\ scripts\ data\ pyproject.toml
#   tesseract\   the UB Mannheim build + afr.traineddata
#   hivemind.ico
param(
    [string]$Python = "python",
    # -Preview: build\Hivemind-UI-Preview.exe instead, the demo-only UI preview
    # (hivemind.iss `Preview`; the owner, 2026-10-22).
    [switch]$Preview,
    # -Source: where the app's code comes from (default: this checkout). A
    # -Preview build is public, so it REQUIRES the scrubbed public export here
    # (tools/export_public.py); MEASURED 2026-10-22: built from the team tree
    # it carried the owner's paths and notes in 48 files.
    [string]$Source = ""
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"      # Invoke-WebRequest is 10x slower with the bar

# ---- pinned downloads (url, sha256); change both together ------------------
$PyVersion = "3.12.10"     # the last 3.12 with Windows binaries
$PyZip     = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip"
$PySha     = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
$TessExe   = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
$TessSha   = "c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9"
# The same afr model the Linux bot reads (Arch tesseract-data-afr 4.1.0).
$AfrData   = "https://raw.githubusercontent.com/tesseract-ocr/tessdata/4.1.0/afr.traineddata"
$AfrSha    = "5ec41cebed3f4a178ee9d72e1112ac9a4a38a7b0ddcafb1266d55d9ded452ea9"
$TessLic   = "https://raw.githubusercontent.com/tesseract-ocr/tesseract/5.4.0/LICENSE"
$TessLicSha = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"

$Here  = $PSScriptRoot
$Root  = Split-Path -Parent $Here
$Build = Join-Path $Here "build"
$Cache = Join-Path $Here "cache"
$App   = Join-Path $Build "app"

function Get-Pinned([string]$Url, [string]$Sha) {
    $file = Join-Path $Cache (Split-Path -Leaf $Url)
    if (-not (Test-Path $file)) {
        Write-Host "downloading $Url"
        Invoke-WebRequest -Uri $Url -OutFile $file
    }
    $got = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLower()
    if ($got -ne $Sha) {
        Remove-Item $file
        throw "$Url has sha256 $got, expected $Sha"
    }
    return $file
}

function Invoke-Checked([string]$Exe, [string[]]$ArgList) {
    & $Exe @ArgList
    if ($LASTEXITCODE -ne 0) { throw "$Exe $ArgList exited $LASTEXITCODE" }
}

if (Test-Path $Build) { Remove-Item -Recurse -Force $Build }
New-Item -ItemType Directory -Force $App, $Cache | Out-Null

# ---- 1. the embeddable Python ---------------------------------------------
$py = Join-Path $App "python"
Expand-Archive (Get-Pinned $PyZip $PySha) -DestinationPath $py
# Its ._pth file is sys.path, whole: the stdlib zip, site-packages, and our
# src (so `pythonw -m hivemind.gui` works). `import site` turns on .pth files.
# It also means isolated mode: PYTHONPATH and the registry are ignored, so a
# Python the user installed themselves cannot leak in.
Set-Content -Encoding ascii (Join-Path $py "python312._pth") @(
    "python312.zip", ".", "Lib\site-packages", "..\src", "import site")

# ---- 2. the wheels, pinned and hash-checked --------------------------------
$site = Join-Path $py "Lib\site-packages"
Invoke-Checked $Python @("-m", "pip", "install", "--disable-pip-version-check",
    "--no-deps", "--only-binary=:all:", "--require-hashes",
    "--platform", "win_amd64", "--python-version", "3.12", "--implementation", "cp",
    "--target", $site, "-r", (Join-Path $Here "requirements-windows.txt"))
if (Test-Path "$site\bin") { Remove-Item -Recurse -Force "$site\bin" }   # launchers for the build's Python

# ---- 3. the app: the repo layout, minus tests/docs/tools/var ---------------
if ($Preview -and -not $Source) { throw "-Preview needs -Source <the public export>: a public build never packages the team tree" }
$Src = if ($Source) { $Source } else { $Root }
Copy-Item -Recurse (Join-Path $Src "src\hivemind") (Join-Path $App "src\hivemind")
New-Item -ItemType Directory -Force (Join-Path $App "scripts") | Out-Null
Copy-Item (Join-Path $Src "scripts\*.py") (Join-Path $App "scripts")
Copy-Item -Recurse (Join-Path $Src "data") (Join-Path $App "data")
Copy-Item (Join-Path $Src "pyproject.toml") $App
Get-ChildItem -Recurse -Directory -Filter "__pycache__" $App | Remove-Item -Recurse -Force
Remove-Item (Join-Path $App "data\calib\*.local.yaml") -ErrorAction SilentlyContinue  # this PC's calibration

# ---- 4. Tesseract: unpacked from the UB Mannheim installer with 7-Zip ------
# (unpacking, not running it: no admin prompt, no uninstall entry, nothing in
# the registry). Tesseract is Apache 2.0; its DLLs are permissive or LGPL
# libraries shipped as separate files, which their licences allow.
$sevenZip = (Get-Command 7z -ErrorAction SilentlyContinue).Source
if (-not $sevenZip) { $sevenZip = "$env:ProgramFiles\7-Zip\7z.exe" }
if (-not (Test-Path $sevenZip)) { throw "7-Zip is needed to unpack Tesseract (choco install 7zip)" }
$unpacked = Join-Path $Build "tesseract-unpacked"
Invoke-Checked $sevenZip @("x", "-y", "-bso0", "-o$unpacked", (Get-Pinned $TessExe $TessSha))
$found = Get-ChildItem -Recurse -File -Filter "tesseract.exe" $unpacked | Select-Object -First 1
if (-not $found) { throw "no tesseract.exe in the UB Mannheim installer" }
$tess = Join-Path $App "tesseract"
New-Item -ItemType Directory -Force (Join-Path $tess "tessdata") | Out-Null
Copy-Item $found.FullName $tess
Copy-Item (Join-Path $found.DirectoryName "*.dll") $tess
$configs = Join-Path $found.DirectoryName "tessdata\configs"
if (-not (Test-Path $configs)) { throw "no tessdata\configs beside tesseract.exe" }
Copy-Item -Recurse $configs (Join-Path $tess "tessdata\configs")     # `tsv` (vision/amulet)
Copy-Item (Get-Pinned $AfrData $AfrSha) (Join-Path $tess "tessdata\afr.traineddata")
Copy-Item (Get-Pinned $TessLic $TessLicSha) (Join-Path $tess "LICENSE-tesseract.txt")
Remove-Item -Recurse -Force $unpacked

# ---- 4b. prune what the app never loads (ROADMAP U15c) ----------------------
# installer\prune.py holds the list, one commented line per item (what it is,
# why the app never loads it, what it saves), shared with build-linux.sh; it
# also cuts the debug sections off libtesseract and fails if anything left
# still imports a removed DLL. MEASURED 2026-10-26 (a -Preview build): app
# folder 626.7 -> 273.5 MB, the .exe 156.4 -> 77.3 MB, selftest passing.
# Before the selftest, so the selftest checks the folder that ships.
Invoke-Checked $Python @((Join-Path $Here "prune.py"), $App)

# ---- 5. icon and wizard images (with the app's own Python: it has cv2) ----
# -B everywhere below: no __pycache__ written into the app folder.
$exe = Join-Path $py "python.exe"
Invoke-Checked $exe @("-B", (Join-Path $Here "make_icon.py"), $Build)
Copy-Item (Join-Path $Build "hivemind.ico") $App

# ---- 6. prove it before packing it -----------------------------------------
$version = (& $exe -B -m hivemind.gui --version).Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) { throw "--version failed" }
Invoke-Checked $exe @("-B", "-m", "hivemind.gui", "--selftest")
$var = Join-Path $App "var"                 # whatever the selftest wrote there
if (Test-Path $var) { Remove-Item -Recurse -Force $var }

# ---- 7. the installer --------------------------------------------------------
# WHERE ISCC IS. MEASURED 2026-10-22 on Windows 11: `choco install innosetup`
# (6.x) now installs per user, to %LOCALAPPDATA%\Programs\Inno Setup 6, and
# puts an ISCC.exe shim on PATH -- not Program Files (x86). Without admin the
# old fallback (choco install again) failed too. PATH first, then both folders.
function Find-Iscc {
    $onPath = (Get-Command ISCC -ErrorAction SilentlyContinue).Source
    if ($onPath) { return $onPath }
    foreach ($dir in @("${env:ProgramFiles(x86)}\Inno Setup 6",
                       "$env:LOCALAPPDATA\Programs\Inno Setup 6")) {
        $exe = Join-Path $dir "ISCC.exe"
        if (Test-Path $exe) { return $exe }
    }
    return $null
}
$iscc = Find-Iscc
if (-not $iscc) {
    Invoke-Checked "choco" @("install", "innosetup", "-y", "--no-progress")
    $iscc = Find-Iscc
}
if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) not found: choco install innosetup" }
$isccArgs = @("/Q", "/DAppVersion=$version", "/DAppDir=$App", "/DImages=$Build", "/O$Build")
$outName = "Hivemind-Setup.exe"
if ($Preview) { $isccArgs += "/DPreview"; $outName = "Hivemind-UI-Preview.exe" }
Invoke-Checked $iscc ($isccArgs + @((Join-Path $Here "hivemind.iss")))
Write-Host "built $(Join-Path $Build $outName) (Hivemind $version)"
