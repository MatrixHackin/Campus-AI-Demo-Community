# Vibe Coding 开发手册

本手册按使用方式分类，每类只保留一种在国内较容易落地的方案。修改本文件后，请重新构建/重启前端应用。

## 平台应用访问路径规范

平台后续会将用户容器中的 Web 服务按下面的路径开放：

```text
https://gpunion.hkust-gz.edu.cn/apps/{app_name}/
```

因此，应用必须满足以下二选一要求：

### 推荐：使用平台模板

优先使用平台提供的前端/全栈应用模板。模板会预留应用访问前缀配置，避免静态资源路径错误。

### 自行开发：配置 Base Path

如果自行创建 Next.js、Vite、React、Vue 等前端应用，需要把应用的 Base Path 配置为：

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

如果不配置 Base Path，页面 HTML 可能可以打开，但静态资源会请求到根路径，例如：

```text
/_next/static/...
/assets/...
```

这些请求不会进入当前应用路径，可能导致页面样式、脚本或路由加载失败。

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

## 方式一：AI IDE - Trae

适合希望开箱即用、不想先配置 API 的用户。

### 适用场景

- 新手学习 Vibe Coding。
- 让 AI 解释代码、生成小功能、补充注释和文档。
- 不想自己管理模型 Base URL 和 API Key。

### 使用步骤

1. 打开 Trae 官网：[https://www.trae.ai/](https://www.trae.ai/)
2. 下载并安装对应系统版本。
3. 登录账号。
4. 打开你的项目目录。
5. 在聊天窗口描述需求，例如：

```text
请阅读当前项目，说明前端登录流程和后端认证接口的关系。先不要修改文件。
```

6. 对需要修改的需求，要求 AI 先给计划，再执行：

```text
请新增一个页面。先列出需要修改的文件和实现方案，等我确认后再改代码。
```

### 注意事项

- AI 生成的代码必须人工 review。
- 大改动前先提交 Git。
- 不要把数据库密码、API Key、生产配置粘贴给 AI。

---

## 方式二：VS Code 插件 - Cline + DeepSeek

适合希望在 VS Code 中使用 Agent，并且自己控制 API 成本的用户。

### 需要准备

| 项目 | 内容 |
| --- | --- |
| 编辑器 | VS Code |
| 插件 | Cline |
| API 平台 | DeepSeek |
| Base URL | `https://api.deepseek.com` |
| API 文档 | [DeepSeek API Docs](https://api-docs.deepseek.com/) |
| API Key 入口 | [DeepSeek Platform](https://platform.deepseek.com/) |
| 价格说明 | [DeepSeek Pricing](https://api-docs.deepseek.com/quick_start/pricing/) |

### 购买和创建 API Key

1. 打开 [DeepSeek Platform](https://platform.deepseek.com/)。
2. 注册或登录账号。
3. 进入 API Keys 页面。
4. 创建 API Key。
5. 按平台提示充值或开通计费。
6. 妥善保存 API Key，不要提交到 Git。

### Cline 配置

在 VS Code 安装 Cline 后，打开 Cline 设置：

```text
API Provider: OpenAI Compatible
Base URL: https://api.deepseek.com
API Key: 你的 DeepSeek API Key
Model ID: deepseek-chat
```

Cline 的 OpenAI Compatible 配置说明见：[Cline OpenAI Compatible](https://docs.cline.bot/provider-config/openai-compatible)。

### 推荐用法

先让 Cline 只分析，不修改：

```text
请阅读当前仓库，找出登录页面和认证接口的位置。不要修改文件，只输出结论。
```

确认方向后再让它改：

```text
请按最小改动实现这个需求：...
修改后运行构建，最后列出改动文件。
```

---

## 方式三：终端 Agent - Codex + 阿里云百炼

适合熟悉命令行、希望让 Agent 在终端中读写项目、运行测试的用户。

### 需要准备

| 项目 | 内容 |
| --- | --- |
| 工具 | Codex CLI |
| API 平台 | 阿里云百炼 Model Studio |
| Base URL | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| API Key 环境变量 | `OPENAI_API_KEY` |
| 官方文档 | [阿里云百炼 Codex 文档](https://help.aliyun.com/zh/model-studio/codex) |

### 开通 API

1. 打开阿里云百炼控制台：[https://bailian.console.aliyun.com/](https://bailian.console.aliyun.com/)
2. 登录阿里云账号。
3. 完成实名或企业认证。
4. 开通模型服务。
5. 创建 API Key。
6. 复制 API Key 并保存到本机环境变量。

### 安装 Codex

```bash
npm install -g @openai/codex
codex --version
```

### 配置环境变量

macOS / Linux：

```bash
export OPENAI_API_KEY="你的百炼 API Key"
```

如果需要永久生效：

```bash
echo 'export OPENAI_API_KEY="你的百炼 API Key"' >> ~/.zshrc
source ~/.zshrc
```

### 配置 Codex

编辑：

```text
~/.codex/config.toml
```

示例：

```toml
model_provider = "Model_Studio"
model = "qwen-plus"

[model_providers.Model_Studio]
name = "Model_Studio"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
env_key = "OPENAI_API_KEY"
wire_api = "chat"
```

> 如果你使用的 Codex 或百炼模型要求 `wire_api = "responses"`，请以 [阿里云百炼 Codex 文档](https://help.aliyun.com/zh/model-studio/codex) 为准。

### 使用方式

进入项目目录：

```bash
cd /path/to/project
codex
```

推荐提示词：

```text
请先阅读当前项目结构，不要修改文件。总结启动方式、前后端目录和认证流程。
```

---

## 安全规范

必须遵守：

- 不要把 API Key 写进 Git。
- 不要把 API Key 写进前端代码。
- 不要把 API Key 粘贴给 AI。
- 不要上传 `.env`、数据库密码、生产配置。
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

### API Key 无效

检查：

- Key 是否复制完整。
- 是否多了空格或引号。
- 是否使用了错误平台的 Key。
- 是否已充值或开通模型服务。

### Model Not Found

检查：

- Model ID 是否拼写正确。
- 当前账号是否有该模型权限。
- Base URL 是否和 API 平台匹配。

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
