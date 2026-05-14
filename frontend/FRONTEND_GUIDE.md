# Frontend Guide

这份文档专门帮你看懂 `frontend/`。

目标只有两个：

1. 用最短路径理解前端怎么跑起来
2. 帮你知道以后该从哪里改

---

## 1. 前端整体像什么

可以把前端想成一家“有门厅、有登录台、有控制室”的小系统：

- `main.jsx`：总开关，负责把整个应用启动起来
- `App.jsx`：门厅，决定用户去哪个页面
- `AuthContext.jsx`：前台，统一保存登录状态
- `api/client.js`：快递员，专门负责和后端通信
- `pages/`：真正展示给用户看的页面

所以前端的核心关系是：

```text
页面 -> 调用 Context / API -> 请求后端 -> 更新页面状态
```

---

## 2. 最推荐的阅读顺序

按这个顺序读，最容易懂：

1. `src/main.jsx`
2. `src/App.jsx`
3. `src/context/AuthContext.jsx`
4. `src/api/client.js`
5. `src/pages/LoginPage.jsx`
6. `src/pages/DashboardPage.jsx`
7. `src/pages/LandingPage.jsx`
8. `src/styles/global.css`

---

## 3. 每个文件到底干什么

## 3.1 `src/main.jsx`

这是前端入口。

它做了三件事：

1. 创建 React 根节点
2. 挂上路由系统 `BrowserRouter`
3. 挂上登录状态系统 `AuthProvider`

你可以把它理解为：

**“先把应用启动，再把路由和登录能力装进去。”**

---

## 3.2 `src/App.jsx`

这里专门定义路由。

当前只有 3 个主要页面：

- `/`：首页
- `/login`：登录页
- `/dashboard`：控制台

还有一个兜底规则：

- 其他地址都跳回首页

最关键的一点是：

`/dashboard` 外面包了一层 `ProtectedRoute`

意思是：

- 已登录：可以进入控制台
- 未登录：跳去登录页

---

## 3.3 `src/components/ProtectedRoute.jsx`

它非常简单，只负责“拦一下”。

判断依据不是后端，而是前端本地有没有登录状态。

所以它的作用更像：

**“前端体验保护”**

而不是：

**“真正的安全校验”**

真正的鉴权还是后端做的。

---

## 3.4 `src/context/AuthContext.jsx`

这是前端最关键的文件之一。

它负责统一管理：

- 当前是否登录
- 当前用户是谁
- token 是什么
- 登录时怎么保存
- 退出时怎么清空

### 你可以把它理解成什么？

像“全局用户中心”。

页面不需要自己去读 `localStorage`，只要：

```js
const { user, token, login, logout, isAuthenticated } = useAuth()
```

就能直接使用登录相关能力。

### 它的工作流程

#### 初始化时

- 从 `localStorage` 读取之前保存的会话
- 解析失败就清掉，防止脏数据影响页面

#### 登录时

- 调用 `loginApi`
- 拿到后端返回的 token 和 user
- 保存到 `localStorage`
- 更新 React 状态

#### 退出时

- 清掉 `localStorage`
- 把会话状态设为 `null`

---

## 3.5 `src/api/client.js`

这是所有前端请求后端的统一入口。

它的意义很大，因为它把“请求细节”集中起来了。

### 它解决了什么问题？

#### 1. 统一 API 地址

如果没有配置 `VITE_API_BASE_URL`，它会自动使用：

```text
http://当前访问主机名:8000/api/v1
```

这就是为什么它适合局域网访问。

#### 2. 统一请求格式

默认加上：

- `Content-Type: application/json`

#### 3. 统一错误处理

如果请求失败，就抛出一个更友好的错误信息。

### 当前导出的三个接口

- `login(payload)`
- `createSandbox(token, payload)`
- `getMySandboxes(token)`

所以这个文件可以理解成：

**“前端对后端接口的说明书 + 出口。”**

---

## 3.6 `src/pages/LoginPage.jsx`

这是登录页。

它的逻辑非常标准：

### 维护三个状态

- `form`：表单输入值
- `loading`：是否正在提交
- `error`：错误提示

### 提交时做什么

1. 阻止表单默认刷新
2. 进入 loading
3. 调用 `login(form)`
4. 成功则跳转到 `/dashboard`
5. 失败则显示错误
6. 最后关闭 loading

### 为什么它好懂？

因为这里只有一条主线：

**“填表 -> 提交 -> 成功跳转 / 失败报错”**

---

## 3.7 `src/pages/DashboardPage.jsx`

这是控制台页面，也是前端业务最集中的地方。

它主要完成两件事：

### 1. 加载我的沙盒列表

页面进入后会调用：

- `getMySandboxes(token)`

然后把结果放进：

- `sandboxes`

### 2. 创建新的沙盒

点击按钮后会调用：

- `createSandbox(token, { image })`

然后：

- 更新成功消息
- 重新拉取列表

### 这个页面最值得你看懂的状态

- `sandboxes`：沙盒列表
- `busy`：按钮 loading
- `message`：成功提示
- `error`：错误提示
- `image`：当前输入的镜像名

### 为什么这里写 `displayName`

这行代码：

```js
const displayName = user?.display_name || user?.username || '开发者'
```

本质是在做“兜底显示”：

- 优先显示真实名称
- 没有就显示用户名
- 再没有就显示默认文案

这样页面里就不用反复写一长串判断了。

---

## 3.8 `src/pages/LandingPage.jsx`

首页的逻辑最轻，重点是展示。

它本质上是：

- 一些静态文案
- 一些按钮
- 一些卡片

### 为什么这里用了数组 + `map`

比如：

- `highlights`
- `showcaseItems`

这样做的好处是：

- 文案集中
- JSX 更短
- 后续加卡片更方便

这也是 React 里很常见的写法：

**“把重复内容写成数组，再 map 成 UI。”**

---

## 3.9 `src/styles/global.css`

这个文件虽然长，但理解方式不难。

不要一行行死看，按层次看：

### 第一层：主题变量

例如：

- `--bg`
- `--panel`
- `--text-muted`
- `--primary`

这是整套视觉风格的基础。

### 第二层：通用组件

例如：

- `.glass-panel`
- `.btn`
- `.brand-mark`

这些类会在多个页面复用。

### 第三层：布局

例如：

- `.hero-layout`
- `.login-layout`
- `.dashboard-grid`

这类样式决定页面是几栏、间距多大。

### 第四层：具体模块

例如：

- `.sandbox-item`
- `.status-chip`
- `.feature-card`

这是针对某一块 UI 的样式。

### 第五层：响应式

最下面两个 `@media` 是给平板和手机用的。

---

## 4. 前端的两条主链路

## 4.1 登录链路

```text
LoginPage
  -> useAuth().login()
  -> api/client.js 的 login()
  -> 后端 /auth/login
  -> 返回 token + user
  -> AuthContext 保存到 localStorage
  -> 跳转到 /dashboard
```

## 4.2 创建沙盒链路

```text
DashboardPage
  -> createSandbox(token, { image })
  -> api/client.js
  -> 后端 /sandboxes
  -> 返回创建结果
  -> 页面显示成功提示
  -> 再次拉取沙盒列表
```

---

## 5. 为什么说现在的前端结构是清晰的

因为职责分得很自然：

- `pages/`：负责“展示和交互”
- `context/`：负责“全局状态”
- `api/`：负责“请求后端”
- `components/`：负责“通用组件”
- `styles/`：负责“统一样式”

这就是一个小型 React 项目很舒服的结构。

---

## 6. 我帮你做的“精简”思路是什么

不是单纯把代码变短，而是让代码：

- 少重复
- 好理解
- 以后好改

例如现在前端里：

- 重复卡片内容改成数组 + `map`
- 重复用户名展示改成 `displayName`
- 默认镜像抽成 `DEFAULT_IMAGE`

这类改动都属于：

**“减少重复，保留直观”**

---

## 7. 你后续该怎么继续完善前端

建议按优先级做：

### 第一阶段

1. 登录过期后自动退出
2. 请求失败支持重试
3. 控制台增加“刷新列表”按钮

### 第二阶段

4. 把 API 请求进一步拆成更清晰的模块
5. 给表单加更明确的校验
6. 增加空态 / 加载态 / 异常态

### 第三阶段

7. 引入测试
8. 引入 ESLint / Prettier
9. 视情况引入 React Query 管理异步请求

---

## 8. 一句话理解整个前端

这个前端本质上就是：

**用 React 做页面，用 Context 管登录，用 API 模块连后端，用路由把页面串起来。**
