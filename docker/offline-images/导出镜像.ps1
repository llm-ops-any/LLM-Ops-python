# CR-16111410 / AC-01 AC-02：把 docker-compose.yaml 依赖的镜像导出为离线 tar 包
# 用法（在 docker/ 下执行，脚本自己会切到 docker/）：
#   powershell -ExecutionPolicy Bypass -File offline-images\导出镜像.ps1
# 设计要点：
#   - 清单唯一来源是 `docker compose config --images`，不手写第二份列表（compose 改版本号后重跑即可）；
#   - 本地缺任何一个镜像就直接报错，不静默漏包；
#   - 幂等：重跑覆盖同名 tar；旧日期的包不自动删（是否清理由人决定）。
[CmdletBinding()]
param(
    # 包输出目录，默认就是脚本所在目录 docker/offline-images
    [string]$OutDir = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'

# 脚本在 docker/offline-images/ 下，compose 必须在 docker/ 下执行才能读到 .env
$dockerDir = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $dockerDir 'docker-compose.yaml'))) {
    throw "未找到 $dockerDir\docker-compose.yaml —— 请确认脚本仍在 docker/offline-images/ 下"
}
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }

Push-Location $dockerDir
try {
    # 1) 清单：compose 唯一来源，去重排序
    Write-Host '[1/5] 从 docker compose 取镜像清单 ...'
    $images = @(docker compose config --images 2>$null | Sort-Object -Unique)
    if ($LASTEXITCODE -ne 0 -or $images.Count -eq 0) {
        throw '未能从 docker compose 取到镜像清单（先确认 docker/.env 存在且 compose 可用）'
    }
    $images | ForEach-Object { Write-Host "      - $_" }

    # 2) 缺包即停：先收集全部缺失项再抛错，避免「导到一半才发现少一个」
    Write-Host '[2/5] 检查本地镜像是否齐全 ...'
    $missing = @()
    foreach ($img in $images) {
        $id = docker image inspect $img --format '{{.Id}}' 2>$null
        if (-not $id) { $missing += $img }
    }
    if ($missing.Count -gt 0) {
        throw ("本地缺少以下镜像，先在能联网的机器上 docker pull / docker compose build 再导出：`n  " + ($missing -join "`n  "))
    }

    # 3) 分组：本地构建的 llmops-* 与上游公共镜像分开，前者变、后者很少变
    $appImages = @($images | Where-Object { $_ -like 'llmops-*' })
    $thirdImages = @($images | Where-Object { $_ -notlike 'llmops-*' })
    $stamp = Get-Date -Format 'yyyyMMdd'

    # 应用包版本号取 llmops-api 的 tag；取不到就退化成日期，保证不因命名规则失败而中断导出
    $appVersion = ($appImages | Where-Object { $_ -like 'llmops-api:*' } | Select-Object -First 1)
    if ($appVersion) { $appVersion = ($appVersion -split ':', 2)[1] } else { $appVersion = $stamp }

    $plan = @()
    if ($appImages.Count -gt 0) {
        $plan += [pscustomobject]@{ File = "llmops-app-$appVersion.tar"; Images = $appImages }
    }
    if ($thirdImages.Count -gt 0) {
        $plan += [pscustomobject]@{ File = "llmops-thirdparty-$stamp.tar"; Images = $thirdImages }
    }

    # 4) 导出
    Write-Host '[3/5] 导出镜像（GB 级写入，耐心等）...'
    foreach ($item in $plan) {
        $target = Join-Path $OutDir $item.File
        Write-Host ("      docker save -> {0}  ({1} 个镜像)" -f $item.File, $item.Images.Count)
        $saveList = @($item.Images)
        docker save -o $target $saveList
        if ($LASTEXITCODE -ne 0) { throw "docker save 失败：$($item.File)" }
    }

    # 5) 校验清单：导入前逐条核对，避免半包/传坏
    Write-Host '[4/5] 生成 SHA256SUMS.txt ...'
    $lines = foreach ($item in $plan) {
        $target = Join-Path $OutDir $item.File
        $hash = (Get-FileHash -Path $target -Algorithm SHA256).Hash.ToLower()
        '{0}  {1}' -f $hash, $item.File
    }
    $lines | Set-Content -Path (Join-Path $OutDir 'SHA256SUMS.txt') -Encoding ASCII

    # 6) 汇总
    Write-Host '[5/5] 完成，产出：'
    foreach ($item in $plan) {
        $target = Join-Path $OutDir $item.File
        $mb = [math]::Round((Get-Item $target).Length / 1MB, 1)
        Write-Host ("      {0}  {1} MB   <- {2}" -f $item.File, $mb, ($item.Images -join ', '))
    }
    Write-Host ("      校验清单：{0}" -f (Join-Path $OutDir 'SHA256SUMS.txt'))
}
finally {
    Pop-Location
}
