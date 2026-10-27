# 离谱法庭 · 书记员服务启动脚本（Windows PowerShell）
# 用法：
#   .\run.ps1             启动服务（默认 0.0.0.0:8899）
#   .\run.ps1 -InitDb     先执行 schema.sql 建库建表，再启动
#   .\run.ps1 -InitOnly   只初始化数据库
param(
    [switch]$InitDb,
    [switch]$InitOnly
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'

if (-not (Test-Path 'config.env')) {
    Copy-Item 'config.example.env' 'config.env'
    Write-Host '[离谱法庭] 已从 config.example.env 生成 config.env，请按需修改数据库密码。'
}

# 优先使用本地虚拟环境
$python = 'python'
if (Test-Path '.venv\Scripts\python.exe') {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
}

if (-not (Test-Path '.venv') ) {
    Write-Host '[离谱法庭] 提示：建议先执行 python -m venv .venv 并 pip install -r requirements.txt'
}

if ($InitOnly) { & $python app.py --init-db --only-init; exit $LASTEXITCODE }
if ($InitDb)   { & $python app.py --init-db; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }

& $python app.py