# CR-16111410 / AC-05：在新机器上从离线 tar 包恢复镜像
# 用法（把整个 offline-images 目录与仓库一起拷到新机器，在 docker/ 下执行）：
#   powershell -ExecutionPolicy Bypass -File offline-images\导入镜像.ps1
# 设计要点：
#   - 先校验 SHA256，不通过立刻停（几百 MB 的包传坏一半，docker load 会在中途才报错）；
#   - 同名 tag 会被覆盖成包内版本，属预期；
#   - 只负责「镜像到位」，起服务仍按 00规则/部署规范.md 第三节。
[CmdletBinding()]
param(
    [string]$InDir = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'

$sumFile = Join-Path $InDir 'SHA256SUMS.txt'
if (-not (Test-Path $sumFile)) { throw "缺少校验清单：$sumFile" }

# 1) 校验：逐条比 SHA256
Write-Host '[1/3] 校验 SHA256 ...'
$bad = @()
foreach ($line in Get-Content $sumFile) {
    if (-not $line.Trim()) { continue }
    $parts = $line -split '\s{2,}', 2
    if ($parts.Count -ne 2) { throw "SHA256SUMS.txt 行格式不对：$line" }
    $expect = $parts[0].Trim()
    $file = Join-Path $InDir $parts[1].Trim()
    if (-not (Test-Path $file)) { $bad += "缺文件：$($parts[1])"; continue }
    $actual = (Get-FileHash -Path $file -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $expect) { $bad += "哈希不符：$($parts[1])" } else { Write-Host "      OK  $($parts[1])" }
}
if ($bad.Count -gt 0) { throw ("校验未通过，重新拷贝后再试：`n  " + ($bad -join "`n  ")) }

# 2) 导入
Write-Host '[2/3] docker load ...'
Get-ChildItem -Path $InDir -Filter '*.tar' | Sort-Object Name | ForEach-Object {
    Write-Host "      $($_.Name)"
    docker load -i $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "docker load 失败：$($_.Name)" }
}

# 3) 结果：把这套环境需要的镜像列出来，人眼确认齐全再起服务
Write-Host '[3/3] 已就位的镜像：'
$dockerDir = Split-Path -Parent $InDir
Push-Location $dockerDir
try {
    $images = @(docker compose config --images 2>$null | Sort-Object -Unique)
    foreach ($img in $images) {
        $id = docker image inspect $img --format '{{.Id}}' 2>$null
        if ($id) { Write-Host ("      OK  {0}" -f $img) } else { Write-Host ("      缺  {0}" -f $img) }
    }
}
finally { Pop-Location }

Write-Host ''
Write-Host '镜像到位。起服务（docker/ 下）：'
Write-Host '  1) 准备 docker/.env（见根目录 环境变量配置说明.md，模板 docker/.env.example）'
Write-Host '  2) docker compose up -d          # 不要加 --build'
Write-Host '  3) docker compose restart llmops-nginx'
Write-Host '  4) curl.exe -s http://localhost/api/ping'
