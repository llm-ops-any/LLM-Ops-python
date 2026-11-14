# 离线镜像包（换机 / 无网环境用）

> 归属：`CR-16111410`。用途：把 `docker/docker-compose.yaml` 依赖的镜像带到**不能或不想联网拉镜像**的机器上。
> 规则出处：`开发文档/00规则/部署规范.md`「离线镜像（换机 / 无网环境）」。

## 一、包里有什么

| 文件 | 内容（镜像） | 实测体积 |
|---|---|---|
| `llmops-app-0.1.0.tar` | `llmops-api:0.1.0`、`llmops-ui:0.1.0` | 489.2 MB |
| `llmops-thirdparty-20261114.tar` | `nginx:latest`、`postgres:15-alpine`、`redis:6-alpine`、`semitechnologies/weaviate:1.28.4` | 265.6 MB |
| `SHA256SUMS.txt` | 上面两个包的 SHA256 | — |
| `导出镜像.ps1` | 在本机重新生成包（清单自动取自 compose） | — |
| `导入镜像.ps1` | 在新机器校验 + `docker load` | — |

镜像集合**以 `docker compose config --images` 为准**（去重后 6 个），不是手写列表。
体积比 `docker images` 显示的「虚拟大小」小得多，是因为 Docker 29（containerd 镜像存储）导出的是 OCI 布局、
层为压缩 blob，同一层只存一份。

## 二、在新机器上装（三步）

```powershell
# 0) 前置：已装 Docker Desktop，仓库已拷到本机（离线包随仓库目录一起拷）
cd <仓库路径>\docker

# 1) 校验 + 导入（脚本会先比 SHA256，不一致立即停）
powershell -ExecutionPolicy Bypass -File offline-images\导入镜像.ps1

# 2) 准备凭证：模板复制后逐项填（该文件不进仓库）
Copy-Item .env.example .env
notepad .env

# 3) 起服务（不要加 --build，镜像已经在本地）
docker compose up -d
docker compose restart llmops-nginx      # 重建/导入 api 后必须做，否则全站 502
```

验收最小 4 条（完整 8 条见 `开发文档/00规则/团队配置.md`）：

```powershell
curl.exe -s http://localhost/api/ping
curl.exe -s -o NUL -w "%{http_code}" http://localhost/home
docker logs llmops-api --tail 100
docker compose ps
```

> **数据要不要带？** 本包只有镜像，**不含数据**。库数据另有一份 SQL 快照：
> `docker/postgres/llmops_data.sql`（见 `CR-16111409`，被 `.gitignore` 排除，需手工拷）。
> 放进 `docker/postgres/` 后，**空数据卷**首次启动会自动灌入。

## 三、离线包覆盖不到的部分（必须知道）

1. **`docker/.env` 不在包里**（含密钥），必须在新机器手工填：取值见根目录 `环境变量配置说明.md`。
2. **不能 `--build` 重建**：`python:3.10-slim-bookworm`、`node:20` 等构建期基础镜像本机没有、也没导出。
   新机器要重建镜像时**仍需联网**拉基础镜像；只跑服务则不需要。
3. **镜像不含数据**：`docker/volumes/` 下的 db / redis / weaviate 数据不在包内。
4. **包会过期**：镜像是对源码某一刻的快照。改了 `api/` 或 `ui/` 代码要跑一次
   `docker compose build llmops-api`（或 `llmops-ui`）后，**重跑导出脚本**，否则包与源码不一致。

## 四、什么时候要重跑导出

| 改了什么 | 要重导哪个包 |
|---|---|
| `api/**` 或模型 YAML（`build llmops-api` 之后） | `llmops-app-*.tar` |
| `ui/**`（`build llmops-ui` 之后） | `llmops-app-*.tar` |
| `docker-compose.yaml` 里的镜像版本（redis / postgres / weaviate / nginx） | `llmops-thirdparty-*.tar` |

```powershell
cd <仓库路径>\docker
powershell -ExecutionPolicy Bypass -File offline-images\导出镜像.ps1
```

## 五、手工校验包（不用脚本时）

```powershell
Get-FileHash .\offline-images\llmops-app-0.1.0.tar -Algorithm SHA256
Get-Content .\offline-images\SHA256SUMS.txt
```

Linux / macOS 上等价：`sha256sum -c SHA256SUMS.txt`。

## 六、为什么不进版本库

`docker/offline-images/*.tar` 已被 `.gitignore` 排除：约 750 MB，且是生成物；入 git 会让仓库不可用。
分发走 U 盘 / 网盘 / 内网共享，配合 `SHA256SUMS.txt` 校验即可。
