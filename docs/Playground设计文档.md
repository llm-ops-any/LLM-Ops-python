# 开放 API Playground —— 设计文档

> 状态：待复核 ｜ 日期：2026-10-16 ｜ 涉及：`ui/`（主）、`api/`（仅新增 stop 端点）

## 1. 背景与目标

「开放 API」当前只有 `POST /openapi/chat`，前端「快速开始」页（`ui/src/views/openapi/IndexView.vue`）只静态展示 curl 与响应示例，无法真发请求。导致：第三方调不通时只能手搓 curl 排查；文档示例已与实际实现不一致；未来加端点没有统一试跑入口。

新增 **Playground** 页面，目标三点：

1. 用**真实 API Key 走完整鉴权链路**发请求，可看原始请求 / 原始 SSE 事件流 / 原始错误码，用于给第三方排障；
2. **端点元数据驱动**，加端点只加一条数据；
3. 「快速开始」与 Playground **共用同一份元数据**，消除文档漂移。

## 2. 范围

**做**：① `/openapi/playground` 路由 + 「秘钥」之后的菜单；② 元数据表 `endpoints.ts`（含新增的 stop 端点）；③ 元数据驱动表单（Key/应用选择、字段联动）；④ 直连 `/api/openapi/chat`，流式 + 非流式；⑤ 响应三视图；⑥ 多轮会话与重置；⑦ 后端新增 stop 端点；⑧ 「快速开始」curl 改由元数据生成并修正错误；⑨ `vite.config.ts` 加 dev 代理。

**不做**：自由请求构造器；后端端点自描述接口；API Key 的增删改；改动既有 `chat` 行为；解决 CORS。

## 3. 已验证的技术前提（读码确认）

**3.1 浏览器只带 API Key 即可通过鉴权**
`openapi_handler.py` L24 的 `@login_required` 走 `Middleware.request_loader`（`middleware.py` L27-53），它按蓝图分流：`blueprint == "openapi"` 时用 `Authorization: Bearer <api_key>` 查 `api_keys` 表换账号。`/openapi/chat` 注册在 `openapi_bp`（`router.py` L326-330）。
→ **反向约束：绝不能带 `access_token`**，否则后端会拿 JWT 去查 `api_keys` 表，必然报 `该秘钥不存在或未激活`。

**3.2 同源直连可行**
`ui/Dockerfile` L18 注入 `VITE_API_PREFIX=/api`；`docker/nginx/conf.d/default.conf` 将 `/api/` 转发到后端并去掉前缀；`proxy.conf` 已配 `proxy_buffering off`，SSE 不被缓冲。→ 零后端/网关改动即可直连。

**3.3 现有文档示例有错（本次顺手修正）**
`ui/src/views/openapi/quick-start.ts`：L2/L81 的 Key 写成 `pat_...`，实际 `ApiKeyService.generate_api_key()`（L78-81）生成的是 `llmops-v1/...`；L1/L80 的 URL `https://localhost:5000/openapi/chat` 实际应为 `<origin>/api/openapi/chat`。

**3.4 未授权响应是 HTTP 200**
`pkg/response/response.py` L24-26 的 `json()` 固定返回 `jsonify(data), 200`，未授权由异常转成业务码：`{"code":"unauthorized","message":"该秘钥不存在或未激活","data":{}}`。
→ 前端**必须看 `body.code`**，不能看 HTTP 状态码。而这些 message（`请登录后尝试` / `验签格式失败` / `该秘钥不存在或未激活`）本身就是最好的排障提示，应原样展示。

**3.5 流式事件格式**
`openapi_service.py` L194 输出 `event: <name>\ndata:{json}\n\n`，data 固定含 `event/thought/observation/tool/tool_input/answer/latency/id/end_user_id/conversation_id/message_id/task_id`。
`agent_message` 是**逐 token 增量**（L170-180 叠加），前端需自行累加；`ping` 是 10 秒心跳（`agent_queue_manager.py` L64-71），无业务含义；结束事件为 `agent_end/stop/error/timeout`（L98-100）。**每个事件都带 `task_id`**，前端可取用。

**3.6 请求参数约束**（`openapi_schema.py`）

| 字段 | 必填 | 默认 | 约束 |
|---|---|---|---|
| `app_id` | 是 | — | UUID |
| `query` | 是 | `""` | 非空 |
| `stream` | 否 | **`True`** | 布尔 |
| `end_user_id` | 否 | `""` | UUID |
| `conversation_id` | 否 | `""` | UUID；**传了它则 `end_user_id` 必须非空**（L31-42） |

最后一条是联动规则，表单必须自动满足（§5.3），否则用户会撞上莫名的 `validate_error`。

**3.7 停止机制 —— 决定 stop 端点怎么写**
`AgentQueueManager`：起任务时写归属缓存 `generate_task_belong:{task_id}` = `{user_prefix}-{user_id}`，`user_prefix` 为 `"account"` 当且仅当 `invoke_from ∈ {WEB_APP, DEBUGGER, ASSISTANT_AGENT}`（L128-137）；`set_stop_flag`（L145-166）**比对归属键**，一致才写停止标记；`listen()` 每轮检查标记 → publish `STOP` → 结束流（L81-91）。

**关键事实**：开放 API 的 chat 构造 `AgentConfig` 时用的是 `user_id=account.id` + `invoke_from=InvokeFrom.DEBUGGER`（`openapi_service.py` L141-142），任务归属键即 `account-{account_id}`。
→ **stop 端点仅凭 API Key 就能完成归属校验，无需额外参数。**

> ⚠️ 已知耦合（如实记录，本次不改）：开放 API 与「应用调试页面」共用 `InvokeFrom.DEBUGGER`，同账号内两者任务归属键无法区分 —— 知道 `task_id` 就能停掉同账号的调试任务。因 `task_id` 为随机 UUID 且限本账号，风险可接受。若将来把 chat 改成 `InvokeFrom.SERVICE_API`，需同步调整 `user_prefix` 白名单，且 stop 要改用 `end_user.id`（届时必须由调用方传 `end_user_id`）。

## 4. 总体架构

```
路由 /openapi/playground        ←「Playground」新导航（排在「秘钥」后）
├─ PlaygroundView.vue            组装页：端点切换 + 左表单/右响应，持有会话状态
│   ├─ RequestForm.vue           ← 完全由 endpoints.ts 渲染，不认识任何具体端点
│   └─ ResponsePanel.vue         ← 三视图 Tab
└─ services/openapi-playground.ts
     · 直连 fetch(`${apiPrefix}${path}`)，Header 只放 Bearer <API Key>
     · stream=true → 自研 SSE 消费：同时回调「解析后事件」与「原始文本」
     · stream=false → 普通 JSON
```

分层意图：**`endpoints.ts` 是唯一「认识端点」的地方**，组件全程只与元数据打交道。

## 5. 前端设计

### 5.1 文件清单

**新增**：`ui/src/views/openapi/playground/` 下 `PlaygroundView.vue`、`endpoints.ts`（另导出 `buildCurl()` / `buildRequest()` 两个纯函数）、`components/RequestForm.vue`、`components/ResponsePanel.vue`；以及 `ui/src/services/openapi-playground.ts`。

**改动**：`router/index.ts` 加路由（+5 行）；`OpenAPILayoutView.vue` 加 `router-link`（+6 行）；`IndexView.vue` 的 curl 改为调 `buildCurl()`（~4 行）；`quick-start.ts` 删掉两个 shell 常量、保留响应示例（−20 行）；`vite.config.ts` 加 `server.proxy`（+10 行）。

### 5.2 端点元数据

```ts
interface EndpointField {
  name: string; label: string
  in: 'body' | 'path' | 'header'
  type: 'string' | 'boolean' | 'enum'
  required: boolean
  defaultValue?: string | boolean
  placeholder?: string; tip?: string
  optionSource?: 'apps' | 'apiKeys'        // 动态选项来源，页面注册 loader
  showWhen?: { field: string; equals: unknown }
}

interface OpenAPIEndpoint {
  key: string; title: string
  method: 'POST'
  path: string                             // 支持 {task_id} 占位符
  credentialField: string                  // 值用于 Authorization: Bearer，不进 body
  streamField?: string                     // 为 true 时按 SSE 消费
  fields: EndpointField[]
  sample: Record<string, unknown>          // 生成 curl / 文档示例
}
export const openAPIEndpoints: OpenAPIEndpoint[] = [/* chat, stopChat */]
```

**`chat` → `POST /openapi/chat`**：`api_key`(header, 必填, `optionSource:'apiKeys'`, 遮蔽显示)、`app_id`(body, enum, 必填, `optionSource:'apps'`)、`query`(body, string, 必填)、`stream`(body, boolean, 默认 `true`，即 `streamField`)、`end_user_id` 与 `conversation_id`(body, 可选)。

> 后两者在 Playground 里以**只读「会话状态」**呈现（+ 清空按钮），不开放手填 —— 手填必然撞上 §3.6 的联动校验。

**`stopChat` → `POST /openapi/chat/tasks/{task_id}/stop`**：`api_key`(header, 与 chat 共用同一选中值)、`task_id`(path, 必填, 由流式事件自动填充)。

元数据只描述**请求侧**；响应示例仍属文档内容，留在 `quick-start.ts`。

### 5.3 参数表单

- 按 `type` 渲染 `a-input` / `a-switch` / `a-select`（`optionSource` 走注册的 loader）；
- `in==='header'` 不进 body，仅用于拼 `Authorization`；`in==='path'` 用于替换路径占位符，**必填校验前置**（缺失则禁用发送按钮）；
- **联动**：写入 `conversation_id` 时**同时**写入 `end_user_id`，从机制上消除违规组合；
- 发送前做一次与后端对齐的预检（必填 + UUID 格式），错误直接标在字段上，避免白跑请求；
- 按钮：`发送`（loading 时禁用）、`停止`（仅流式且已拿到 `task_id` 时可用）、`清空会话`。

### 5.4 API Key 与应用选择

- 进页面用**登录态**调 `getApiKeysWithPage`，只列 `is_active` 的 Key；下拉显示 `备注 + 前 12 位…`（不完整展示，防肩窥）；
- 支持「手动粘贴」，便于测试非本账号或格式异常的 Key（排障场景）；
- 选中的 Key 存 `sessionStorage`（关页面即失效），**不落 localStorage、不回传后端**；
- 应用列表用登录态调 `getAppsWithPage`。

> ⚠️ 这里存在**两套凭证**：列表接口走现有 `utils/request.ts`（带 `access_token`），业务请求走新的直连封装（带 API Key）。实现时严禁混用。

### 5.5 响应面板三视图

| Tab | 内容 |
|---|---|
| **回答** | `agent_message` 的 `answer` 增量累加（打字机）；下方折叠推理链路：`agent_thought`（思考/工具调用参数）、`agent_action`（工具与观测）、耗时 `latency` |
| **原始事件流** | 逐行追加的 SSE 原文，等宽字体、可复制、可清空。**排障核心**：`ping` 与逐 token 的 `agent_message` 都如实出现 |
| **等价请求** | 元数据 + 当前表单值生成的 curl；默认遮蔽 Key，可显式展开；**「复制」给的是含完整 Key 的版本**并提示「勿外传」—— 否则无法拿去终端复跑，与 §9 验收第 6 条冲突 |

### 5.6 请求与 SSE 消费（不复用 `utils/request.ts`）

不复用的四个理由（均已逐行核对 `request.ts`）：① `ssePost` L110 无条件执行 `options.headers.set('Authorization', access_token)`，会顶掉 API Key；② 若改用 `post`，`baseFetch` L80-82 在 `code === "unauthorized"` 时会 `clearCredential()` 并跳登录页 —— 而这里的 unauthorized 只代表「这个 Key 不行」，不该影响当前登录态；③ 排障需要原始 SSE 文本，而 `handleStream`（L133-195）只回调解析后的 `{event, data}`；④ `baseFetchOptions.headers`（L14-16 单例 `Headers`）在 L31 / L107 只被 `Object.assign` 浅拷贝，复用会污染全局头。

独立实现一个函数，签名要点：

```ts
requestOpenAPI(
  endpoint: OpenAPIEndpoint,
  values: Record<string, unknown>,
  callbacks: { onEvent(e): void; onRawChunk(text: string): void },
  signal?: AbortSignal,
): Promise<{ ok: boolean; raw?: string; parsed?: unknown }>
```

- URL = `apiPrefix` + `path`（替换 `{name}` 占位符）；
- Header 仅 `Authorization: Bearer <credential>` 与 `Content-Type: application/json`，**不带任何 token**；
- `credentials: 'omit'`：真实第三方调用方不会携带本站 cookie（现有封装的 `baseFetchOptions` 是 `'include'`），直连时省去才等价复现对方链路；
- body 只放 `in==='body'` 的字段（跳过空串与 `undefined`）；
- 按响应 `Content-Type` 分流：`text/event-stream` → SSE 解析；`application/json` → 读 JSON（**含 HTTP 200 的业务错误**）；
- SSE 解析沿用项目既有做法（按 `\n\n` 分帧、拆 `event:` 与 `data:`），每帧同时回调 `onEvent` 与 `onRawChunk`。

### 5.7 多轮对话与停止

**多轮**：首次不传 `conversation_id`/`end_user_id` → 后端在响应中回带（流式事件或非流式 body）→ 页面记住 → 后续自动带上。「清空会话」清掉三者及右侧视图。

**停止**：① 流式开始后从首个事件取 `task_id`；② 点「停止」→ 以 API Key 调 `POST /api/openapi/chat/tasks/{task_id}/stop`；③ 服务端写停止标记后流内推送 `event: stop`，前端正常收尾（期间按钮显示「正在停止…」）；④ 若 3 秒内未收到，则本地 `AbortController` 断开兜底，并在视图上如实标注。

## 6. 后端设计（新增 stop 端点）

| 项 | 值 |
|---|---|
| 路径 | `POST /openapi/chat/tasks/<uuid:task_id>/stop` |
| 蓝图 | `openapi_bp`（复用既有 API Key 鉴权，无需新中间件） |
| 参数 | 仅 path 参数 `task_id` |
| 成功响应 | `{"code":"success","message":"停止开放API会话成功","data":{}}` |
| 失败响应 | 同既有端点，由全局异常处理器输出 `unauthorized`/`not_found`/`forbidden` |

**为何不复用内部路径** `/apps/:app_id/conversations/tasks/:task_id/stop`：开放 API 侧 `app_id` 是请求体字段而非路径段，硬套会让调用方多传无意义的 `app_id`；`/openapi/chat/tasks/...` 与 `/openapi/chat` 同前缀，语义清晰。

**实现三处（纯新增）**：

1. `router.py`：在 chat 注册之后 `openapi_bp.add_url_rule("/openapi/chat/tasks/<uuid:task_id>/stop", methods=["POST"], view_func=self.openapi_handler.stop_chat)`；
2. `openapi_handler.py`：`@login_required def stop_chat(self, task_id)` → 调 service → `success_message("停止开放API会话成功")`；
3. `openapi_service.py`：新增 `@classmethod stop_chat(cls, task_id, account)` → `AgentQueueManager.set_stop_flag(task_id, InvokeFrom.DEBUGGER, account.id)`。

**唯一实现要点**：`invoke_from` 与 `user_id` 必须与 §3.7 中 chat 建任务时**完全一致**（`InvokeFrom.DEBUGGER` + `account.id`），否则归属校验失败、标记写不进去 —— 需在代码中加注释说明该耦合来源。

**影响面**：不改动任何既有端点；`set_stop_flag` 对「任务不存在/归属不符」是静默返回（L153-162），故重复停止、停不存在的 `task_id` 都不报错，返回成功即可（与内部 stop 端点一致）。该端点对第三方同样可用，属开放 API 能力增强。「快速开始」页会随元数据自动带上它（在本次范围内）；而 `api/docs/01.项目API文档.md` 的手工补写**不在本次范围**，建议后续单独补。

## 7. 数据流（一次流式对话）

```
用户         表单/页面                  openapi-playground.ts        nginx → api
 │ 选 Key/应用/填 query
 │ 点发送 ──▶ 预检(必填/UUID)
 │           组装 body ─────────────▶ fetch /api/openapi/chat
 │                                    Header: Bearer <api_key>（无 access_token）
 │                                                        ──▶ request_loader 按蓝图分流
 │                                                            key → account
 │           记住首个事件的 task_id    ◀── text/event-stream ──
 │  ←── 回答累加 + 推理步骤 + 原始事件流（逐帧）
 │ 记住 conversation_id / end_user_id（供下一轮）
 │ 点停止 ──▶ POST .../tasks/{task_id}/stop ─────────────▶ set_stop_flag
 │           流内收到 event: stop 正常收尾 ◀────────────────
```

## 8. 错误处理

原则：**一律展示后端原文，不能只弹 toast 吞掉**。

| 场景 | 实际返回 | 页面表现 |
|---|---|---|
| Key 不存在/被禁用 | 200 + `code:"unauthorized"`，message `该秘钥不存在或未激活` | 红色告警 + 引导检查 Key 是否 `llmops-v1/` 开头、是否启用 |
| 缺 Authorization / 非 Bearer | 200 + `code:"unauthorized"` + 格式提示 | 原文展示 |
| 参数校验失败 | 200 + `code:"validate_error"` + 字段级 errors | 逐字段红色标注 |
| 应用不存在/未发布 | 服务层异常对应 code | 原文展示 |
| 流内 `error`/`timeout` | SSE 事件 | 流末尾红色插入 |
| 网络/代理层异常、非 JSON 响应 | fetch reject 或纯文本 | 展示 status + 响应体原文 |
| 停止请求失败 | 同 unauthorized/网络异常 | 提示失败并保留本地断开兜底 |

## 9. 测试与验收

**单测（vitest 已配置，`npm run test:unit`）**：只测纯函数 —— 元数据 → curl 生成、元数据 → 请求体组装、路径占位符替换。这是"单一数据源"正确性的保障（也是选 A 方案的核心收益）。

**手工验收清单**：

1. 正确 Key + 流式 → 回答打字机输出、推理步骤可展开、原始事件流有完整 `ping`/`agent_message`；
2. 关闭 `stream` → JSON 正常渲染；
3. 禁用/伪造格式的 Key → 出现 `unauthorized` 原文提示，**且不被踢回登录页**；
4. 连发两轮 → 第二轮能记住上下文（`conversation_id` 复用生效）；
5. 点「停止」→ 服务端任务终止、收到 `event: stop`；重复停止不报错；
6. 「等价请求」的 curl **可原样在终端执行成功**；
7. 「快速开始」页 curl 已修正（`llmops-v1/...`、`/api/openapi/chat`）且与 Playground 一致；
8. `npm run type-check` 与 `npm run lint` 通过。

## 10. 已知局限

1. **测不出跨域问题**：同源代理调用，真第三方跨域才会踩 CORS，超出本页面能力（会在页面上写明，避免误判）；
2. **停止共享命名空间**：见 §3.7 的 `InvokeFrom.DEBUGGER` 耦合；
3. **`npm run dev` 需代理**：已通过 §5.1 的 `vite.config.ts` 改动解决（原本 `/api/*` 在 dev 下不可用，是项目既有情况）；
4. **Key 在浏览器内**：仅存 `sessionStorage`，属内部排障工具的合理取舍；若未来要给外部用户用，应改为后端代理持有 Key。
