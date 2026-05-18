# Vibe Coding 开发手册

本手册按平台当前工作流编写：先在“工作台”申请容器，再通过应用访问、IDE 连接、WebSSH 或原生 SSH 进入容器开发。修改本文件后，请重新构建/重启前端应用。

## 平台应用访问路径规范

容器内 Web 服务默认需要监听 `3000` 端口。平台会将应用暴露为：

```text
https://gpunion.hkust-gz.edu.cn/apps/{app_name}/
```

因此，前端项目需要把 Base Path 配置为：

```text
/apps/{app_name}
```

例如应用名为 `demo`，访问地址是：

```text
https://gpunion.hkust-gz.edu.cn/apps/demo/
```

则应用 Base Path 应设置为：

```text
/apps/demo
```

如果不配置 Base Path，页面 HTML 可能能打开，但静态资源会请求到根路径，例如 `/_next/static/...` 或 `/assets/...`，导致样式、脚本或路由加载失败。

### Next.js 示例

`next.config.js`：

```js
const nextConfig = {
  basePath: '/apps/demo',
  assetPrefix: '/apps/demo',
}

module.exports = nextConfig
```

`next.config.mjs`：

```js
const nextConfig = {
  basePath: '/apps/demo',
  assetPrefix: '/apps/demo',
}

export default nextConfig
```

修改后需要重新构建或重启应用。

---

## 利用IDE开始 VibeCoding

适合希望在本地编辑器里连接远程容器、保留完整代码补全和 AI 助手体验的用户。工作台容器横栏提供 `VSCode连接` 和 `Cursor连接` 按钮，点击后会尝试调用本机编辑器的 Remote SSH 能力打开容器。

### VS Code + GitHub Copilot

#### 本机准备

1. 安装 VS Code：[https://code.visualstudio.com/](https://code.visualstudio.com/)
2. 安装 Remote - SSH 扩展：[VS Code Remote SSH 文档](https://code.visualstudio.com/docs/remote/ssh)
3. 安装 GitHub Copilot 扩展。
4. 准备 GitHub Copilot 订阅或组织授权：[GitHub Copilot Plans](https://docs.github.com/en/copilot/about-github-copilot/subscription-plans-for-github-copilot)

#### 平台使用

1. 在“工作台”申请容器，设置 `app_name` 和连接密码。
2. 等容器状态为“运行中”。
3. 点击容器横栏的 `VSCode连接`。
4. 浏览器提示打开 VS Code 时选择允许。
5. VS Code 弹出 SSH 密码时，输入申请容器时设置的连接密码。
6. 连接成功后，在远程窗口中打开项目目录，并使用 Copilot Chat 或代码补全辅助开发。

#### 适合任务

- 让 Copilot 解释当前文件或项目结构。
- 根据已有代码补全函数、测试和注释。
- 在 VS Code 终端中运行构建、测试和启动命令。

### Cursor

#### 本机准备

1. 下载 Cursor：[https://cursor.com/download](https://cursor.com/download)
2. 登录 Cursor 账号，并按需开通套餐或用量计费：[Cursor Pricing](https://cursor.com/pricing)
3. 确认本机可以使用 `ssh` 命令。
4. 确认 Cursor 中可使用 Remote SSH 能力；如果首次连接失败，可以先用“复制 SSH”命令在本机终端验证密码和网络。

#### 平台使用

1. 在“工作台”点击容器横栏的 `Cursor连接`。
2. 浏览器提示打开 Cursor 时选择允许。
3. Cursor 弹出 SSH 密码时，输入申请容器时设置的连接密码。
4. 连接成功后，在远程容器内打开项目目录，用 Cursor Chat / Agent 修改代码。

#### 推荐提示词

```text
请先阅读当前项目结构，不要修改文件。总结启动命令、前后端目录和需要注意的配置文件。
```

确认方案后再执行修改：

```text
请按最小改动实现这个需求。修改前先列出计划，修改后运行构建，并说明改动文件。
```

---

## 利用CLI开始 VibeCoding

适合熟悉终端、希望在容器内直接运行 AI CLI、构建命令和测试命令的用户。平台提供两种进入终端的方式。

### 进入容器终端

#### 方式一：WebSSH

1. 在“工作台”找到目标容器。
2. 点击 `WebSSH`。
3. 浏览器会打开 Web 终端。
4. 输入申请容器时设置的连接密码后进入 shell。

WebSSH 适合临时操作、查看日志、运行轻量命令。如果要长时间开发，建议使用本机终端或 IDE Remote SSH。

#### 方式二：复制 SSH

1. 点击容器横栏的 `复制 SSH`。
2. 在本机终端粘贴命令，例如：

```bash
ssh username+app_name@10.120.17.138 -p 2222
```

3. 输入申请容器时设置的连接密码。
4. 进入容器后再启动你的开发工具或项目命令。

### Claude Code CLI

Claude Code 适合在终端中让 Agent 读取项目、规划任务、修改文件并执行命令。

#### 安装

官方文档：[Claude Code CLI reference](https://code.claude.com/docs/en/cli-usage)

常见安装方式：

```bash
npm install -g @anthropic-ai/claude-code
claude --version
```

#### 使用

```bash
cd /path/to/project
claude
```

推荐先让它只分析：

```text
请阅读当前仓库，不要修改文件。总结项目结构、启动方式和主要风险点。
```

确认后再要求它修改：

```text
请按最小改动实现以下需求。先给计划，等我确认后再修改。
```

### Codex CLI

Codex CLI 适合在终端中进行代码阅读、补丁修改、运行测试和提交前检查。

#### 安装

官方入门文档：[OpenAI Codex CLI Getting Started](https://help.openai.com/en/articles/11096431-openai-codex-ligetting-started)

```bash
npm install -g @openai/codex
codex --version
```

#### 配置 API

如果使用 OpenAI 官方 API，按 OpenAI 平台创建 API Key 后设置环境变量：

```bash
export OPENAI_API_KEY="你的 API Key"
```

如果校园网络或预算要求使用国内 OpenAI 兼容平台，例如阿里云百炼、DeepSeek 等，请在 CLI 配置中使用对应平台提供的 `base_url`、模型名和 API Key。平台地址、价格和模型权限变化较快，请以对应服务商官方控制台为准。

#### 使用

```bash
cd /path/to/project
codex
```

推荐提示词：

```text
请先检查当前改动，不要修改文件。指出潜在风险，并给出最小修复计划。
```

---

## 安全规范

必须遵守：

- 不要把 API Key 写进 Git。
- 不要把 API Key 写进前端代码。
- 不要把数据库密码、SSH 密码、生产配置粘贴给 AI。
- 大改动前先提交 Git 或创建分支。
- AI 修改后必须人工 review diff。
- 涉及生产环境时，先在测试环境验证。

推荐 `.gitignore`：

```gitignore
.env
.env.*
!.env.example
*.key
*.pem
```

---

## 排障清单

### IDE 按钮点击后没有反应

检查：

- 本机是否安装 VS Code 或 Cursor。
- 是否安装 Remote - SSH 相关扩展。
- 浏览器是否拦截了自定义协议跳转。
- 先点击 `复制 SSH`，在本机终端确认 SSH 命令可连接。

### SSH 密码错误

检查：

- 密码是否为申请容器弹窗中设置的连接密码。
- 是否连接到了正确的 `app_name`。
- 容器是否仍处于“运行中”。

### 应用页面资源加载失败

检查：

- Web 服务是否监听容器内 `3000` 端口。
- 前端项目是否配置了 `/apps/{app_name}` Base Path。
- 修改 Base Path 后是否重新构建或重启应用。

### API Key 无效

检查：

- Key 是否复制完整。
- 是否多了空格或引号。
- 是否使用了错误平台的 Key。
- 是否已充值或开通模型服务。

### 请求超时

检查：

- 当前网络是否能访问 API 域名。
- 校园或公司网络是否拦截。
- Base URL 是否漏写 `/v1` 或误加 `/v1`。

### 费用异常

建议：

- 开启预算提醒。
- 小任务优先用低成本模型。
- 长任务分阶段执行。
- 不要让 Agent 无限自动重试。
