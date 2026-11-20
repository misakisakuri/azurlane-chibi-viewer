# Build AzurLaneChibiViewer (onedir, windowed).
#
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
#   .\build.ps1 -Python "C:\Python312\python.exe"
#
# Output:
#   dist\AzurLaneChibiViewer\AzurLaneChibiViewer.exe (+ _internal)
#   dist\AzurLaneChibiViewer-win64.zip
#
# onedir 是故意的：onefile 每次启动都要解压到 %TEMP%，慢且容易被安全软件拦截。
# 注意：本文件请保持 UTF-8 with BOM，Windows PowerShell 5.1 才能正确读取中文。

param(
    [string]$Python = "",
    [string]$Name = "AzurLaneChibiViewer"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd.Source }
}
if (-not $Python -or -not (Test-Path $Python)) {
    throw "找不到 Python。请用 -Python 指定解释器，例如: .\build.ps1 -Python C:\Python312\python.exe"
}

& $Python -c "import UnityPy, PIL" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "依赖没装好，先执行: $Python -m pip install -r requirements.txt -r requirements-dev.txt"
}

& $Python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name $Name `
    --icon "$here\assets\app.ico" `
    --distpath "$here\dist" `
    --workpath "$here\build" `
    --specpath "$here\build" `
    --add-data "$here\index.html;." `
    --add-data "$here\app.js;." `
    --add-data "$here\style.css;." `
    --add-data "$here\assets\app.ico;." `
    --add-data "$here\vendor;vendor" `
    --collect-all UnityPy `
    --collect-data archspec `
    --hidden-import texture2ddecoder `
    --hidden-import etcpak `
    --hidden-import astc_encoder `
    --hidden-import lz4.block `
    --hidden-import brotli `
    --exclude-module pandas `
    --exclude-module openpyxl `
    --exclude-module lxml `
    --exclude-module numpy `
    "$here\launcher.py"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with $LASTEXITCODE" }

# PyInstaller 会清空输出目录，构建后再放回用户说明并重新打包
$out = Join-Path $here ("dist\" + $Name)
Copy-Item "$here\使用说明.txt" -Destination $out -Force

$zip = Join-Path $here ("dist\" + $Name + "-win64.zip")
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path $out -DestinationPath $zip -CompressionLevel Optimal

Write-Host "built: $out\$Name.exe"
Write-Host "zip:   $zip"
