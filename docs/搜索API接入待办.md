# 搜索 API 接入待办 · 成长 LLMOps

> **状态**：**暂缓** —— 2026-10-18 张勇决定「先不接」，本文只做清单留存，不含任何代码改动。
> **用途**：将来要把官方搜索 API 接进来时照此开工，不必重新调研 / 重新比价 / 重新踩一遍 HTML 抓取的坑。
> **写给谁**：接手这块开发的 AI（先读本文再动手）＋ 张勇本人。
> **依据**：2026-10-18 张勇提供的四家官方文档摘要 ＋ 本机对现有 `web_search` 实现的实测。
> **凭证边界**：本文**只写环境变量名**，所有 Key 值一律进 `docker/.env`（已被 git 忽略），不进文档、不进代码、不进任何共享库。
> **关联代码**：`api/internal/core/tools/builtin_tools/providers/web_search/`

---

## 1. 背景：现在能搜，但不稳

平台当前的联网检索能力来自内置插件 `web_search`（`providers/web_search/`）：**抓 360 搜索结果页的 HTML，用 BeautifulSoup 解析 `li.res-list` 里的 `.res-title` / `.res-desc`，失败时回退必应**（`li.b_algo` → `h2` + `.b_caption`）。

**能做到的**

- 免密钥、国内直连（不需要代理 / VPN），`{实测 · 2026-10-18}`
- 返回「标题 + 摘要」列表，喂给模型做归纳够用
- 已过滤站内聚合噪音（`AGGREGATION_TITLE_KEYWORDS`：360文库 / 360图片 / 其他人还搜）与摘要尾部的「域名 反馈」

**做不到的（这正是要换官方 API 的理由）**

| 短板 | 后果 |
|---|---|
| 靠 HTML 结构解析 | 引擎一改版就失效，且对方**没有任何 SLA** |
| 只有标题 + 摘要 | 拿不到**来源、发布时间、权威度、相关度分数** |
| 广告与 SEO 垃圾 | 只能靠关键词硬编码过滤（`AGGREGATION_*` / `NOISE_SNIPPETS`），漏网率高 |
| 360 返回加密跳转链接 | **取不到真实 URL**，当前实现干脆不输出链接（对模型无损，但没法溯源） |

> 已排除的方案：Google / DuckDuckGo 在本机网络下不通；必应对中文长查询**过度泛化**（搜「潮汕牛肉丸 品牌 价格」只回「潮汕」旅游攻略），只能当兜底。

---

## 2. 待接入清单

> ⚠️ 张勇 2026-10-18 原文标题写「**5 个**」，正文实际只给了 **4 个**（下表），**第 5 个待补**。补齐后再定最终方案。

| # | 名称 | 接口地址 | 鉴权 | 官方接入形态 | 特点 / 适用场景 |
|---|---|---|---|---|---|
| 1 | **火山引擎 · 豆包搜索** | APIKey 直连（推荐）`https://open.feedcoopapi.com/search_api/web_search`<br>IAM AK/SK `https://mercury.volcengineapi.com?Action=WebSearch&Version=2025-01-01` | `Authorization: Bearer {API_KEY}`，POST JSON | **原生 MCP Server / Skill**（Dify / MaxKB / LobeHub 可直接配） | 返回结构化摘要 + 来源链接 + 发布时间，内置低质网页过滤；**中文新媒体（头条 / 公众号 / 资讯）召回强**；个人认证**每月 500 次免费**。适合 Agent 原型、资讯 / 生活检索 |
| 2 | **阿里云 IQS · UnifiedSearch** | `https://cloud-iqs.aliyuncs.com/search/unified` | `Authorization: Bearer {API_KEY}`，POST | HTTP / 阿里云 SDK / **MCP** / Skill | 自带 **query 改写 + 结果重排 + 广告过滤**，返回带分数的结构化结果；配套 **ReadPage 网页原文抓取**；引擎可选 `CNLiteBasic`（极速便宜）/ `CNAuto`（智能增强，Agent 推荐）。政企 / 新闻 / 电商稳定，生产级高并发友好 |
| 3 | **DeepSeek 搜索** | 无独立搜索 endpoint —— 走 Harness **服务端工具调用**，OpenAI 兼容 BaseURL `https://api.deepseek.com/v1` | `{API_KEY}`（OpenAI 兼容头） | 在 `tool_calls` 里直接调 `search`（search + fetch 一体），MCP 原生支持 | 技术文档 / 开源项目 / 技术资讯检索突出，内置 AIGC 垃圾页过滤，性价比高。适合技术调研、代码助手 |
| 4 | **百度 · 千帆 AppBuilder AI 搜索** | 文档 `https://ai.baidu.com/ai-doc/AppBuilder/pmaxd1hvy`；⚠️ 原文给的接口是短链 `shturl.cc/…`，**真实 endpoint 待核实** | `Authorization: Bearer {API_KEY}`，POST JSON | 控制台建 Key；**支持 MCP** | 国内网页收录最全，百科 / 政务 / 行业资料强；**SEO 垃圾与广告偏多，Agent 侧需自行过滤重排**。有 AI 搜索封装版（自带摘要 + 溯源）与传统原始摘要版两种 |

**共性**：四家**全部支持 MCP**；第 1 / 2 / 4 家同时是标准 `POST + Bearer`，接 HTTP 的成本最低。

### 逐家备注（动手前先看）

1. **火山豆包** —— 优先走 **APIKey 直连**；`IAM AK/SK` 那条需要火山 V4 签名，除非要复用已有 IAM 体系，否则不必碰。
2. **阿里 IQS** —— 真正的加分项是**配套的 ReadPage**：搜索结果只有摘要，做深度调研时还需要抓原文，这一套能一次到位（本项目现有插件没有抓原文能力）。
3. **DeepSeek** —— ⚠️ **它不是「POST 一个搜索接口拿回结果列表」**，而是模型在 `tool_calls` 里自己决定调用 `search`。也就是说：**接它等于换整条模型调用链，不是加一个 HTTP 插件**。作为 `web_search` 的一个 provider 意义有限，应单列为「DeepSeek 模型 + Harness 工具」的整链路评估。
4. **百度千帆** —— 先把文档地址里的真实 endpoint 找出来（原文的 `shturl.cc` 是短链跳转，不能直接写进代码）。

---

## 3. 三种接入形态，本项目怎么选

| 维度 | 内置插件（本项目现有） | API 插件 | MCP |
|---|---|---|---|
| 定义在哪 | 代码仓的 `providers/<name>/` 目录 | 数据库 `api_tool` 表（界面填） | 独立服务进程，自行声明 |
| 进程模型 | 与 api **同进程** | 同进程，向外发 HTTP | **独立进程 / 远程** |
| 协议 | 进程内函数调用 | HTTP/JSON | JSON-RPC（stdio 或 SSE/HTTP） |
| 工具发现 | 启动时扫目录，**静态** | 查库，静态 | `tools/list` **运行时**返回 |
| 改一行要重建镜像 | **要** | 不用（改库即生效） | 不用（重启 MCP 服务即可） |
| 能否跨客户端复用 | 不能 | 不能 | **能**（CodeBuddy / Cursor / Claude 通用） |
| 能否参与画布编排 | **能**（工具下拉、变量绑定、单节点调试） | 能 | 需额外做映射才行 |

**判据**

- 要出现在工作流画布的工具下拉里、能绑定变量、能单节点调试 → **内置插件**
- 只是打一个外部 HTTP 接口、参数常变、不想重建镜像 → **API 插件**
- 要跨客户端共用，或是有状态的长驻服务 → **MCP**

---

## 4. 落地时要改哪些文件

### 方案 A：内置插件（推荐，与现有 `web_search` 完全同构）

1. 新建 `api/internal/core/tools/builtin_tools/providers/<vendor>_search/`，五个文件：
   - `__init__.py` —— 导出工厂函数（`from .xxx import xxx`）
   - `<tool>.py` —— 继承 `langchain_core.tools.BaseTool`，实际请求写在这里；参数用 `pydantic_v1` 的 `BaseModel` 描述
   - `<tool>.yaml` —— `name` / `label` / `description` / `params`（**Key 不写在这里**，`params` 只放用户可填参数）
   - `positions.yaml` —— 列出该 provider 下的工具名
   - `_asset/icon.svg` —— 图标
2. `providers/providers.yaml` 追加 provider 注册项，字段固定为：`name` / `label` / `description` / `icon` / `background` / `category`（搜索类填 `search`）/ `created_at`
3. 密钥：`docker/.env` 加变量 ＋ `docker/docker-compose.yaml` 里 `llmops-api` 与 `llmops-celery` 两个服务的 `environment` 都要加（漏了 celery 侧任务会拿不到）
4. 生效：`docker compose build llmops-api` → `docker compose up -d` → **`docker compose restart llmops-nginx`**（漏这步全站 502）

### 方案 B：API 插件（零代码）

后台插件面板里填 `method` / `url` / `headers` / `params` / `schema`，写入 `api_tool` 表；`Authorization` 放在 headers 里。适合先验证「这个 API 值不值得接」。

### 方案 C：MCP

新增 `providers/mcp/`：一个通用 `BaseTool` 壳，`_run()` 里转发 `tools/call`；启动时 `tools/list` 一遍，把每个远端工具转成一个 `BaseTool` 实例塞进 manager，命名 `mcp__<server>__<tool>` 防重名。这样画布的工具下拉 / 变量引用 / 调试面板都不用改（它们只认 `BaseTool` 接口）。

**两个必须处理的前提**

- 远端 `inputSchema` 要转成 pydantic 模型，否则参数表单渲染不出来
- MCP 返回的 content 数组要**降级成字符串**（`ToolNode` 现在的输出是 string）

---

## 5. 建议的实施顺序

1. 补齐第 5 个搜索 API，确认清单完整
2. **先接火山豆包**（有免费额度、返回结构化字段、官方 MCP 现成）—— 用方案 B 先打通，验证值不值得转方案 A
3. 再评估**阿里 IQS**（生产级 + ReadPage 抓原文，适合做深度调研类应用）
4. 定兜底策略：是「官方 API 优先、360 兜底」，还是「按场景分流」（如资讯走豆包、政企走千帆）
5. DeepSeek 单独做「模型 + Harness 工具」整链路评估，不与其他三家并列

---

## 6. 验收清单（任一家接完都要过）

- [ ] 画布工具下拉能选中该工具，参数表单能正常渲染
- [ ] 单节点调试能返回结果，且结果里带来源链接 / 发布时间（该 API 若提供）
- [ ] **缺 Key 时的行为明确**：是构造期就抛（像 `google_serper`，会让整个请求 500）还是运行时提示（像高德工具包，对话仍正常）—— 两种都要在文档里写清
- [ ] 超时 / 限流 / 失败有兜底，**不要把 500 抛给前端**（前端只会显示「网络请求失败」）
- [ ] 重建镜像后 7 容器全绿、经 nginx 访问不 502、数据表完整
- [ ] 原 `web_search` 的去留已决策（替换 / 降为兜底 / 并存），并同步 `providers.yaml`

---

## 7. 变更记录

- **2026-10-18 建** —— 张勇决定「先不接」，仅将清单与方案留存于本文；同步登记到共享库 `项目记忆\LLMOps.md` §六 / §七，以及 `web_search.py` 顶部 TODO 注释。
