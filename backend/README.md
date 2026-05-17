# Backend / FastAPI

## 功能
- 登录接口（支持 demo 模式，保留自定义数据库接口扩展点）
- 校园 SSO 登录
- 工作台支持 Harbor 镜像展示与默认 devbox 容器申请

## 启动
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 局域网访问
- 默认监听 `0.0.0.0:8000`
- 默认已放行 `localhost`、`127.0.0.1` 以及常见局域网网段的前端 Origin
- 局域网内其他设备可直接访问 `http://你的电脑局域网IP:8000/api/health`
- 如需更严格控制，可在 `.env` 中将 `CORS_ORIGIN_REGEX=` 置空，再自行设置 `CORS_ORIGINS`

## 自定义数据库接入
已内置 MySQL 登录认证仓库，可在 DataGrip 中执行：

```text
sql/mysql_auth.sql
```

然后在 `.env` 中配置：

```env
AUTH_BACKEND=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=campusai
MYSQL_PASSWORD=你的密码
MYSQL_DATABASE=campus_ai
MYSQL_USER_TABLE=users
```

新增用户密码哈希可用：

```bash
python scripts/hash_password.py 你的密码
```

输出结果直接填入 `users.password_hash` 字段。

## 校园 SSO 登录

后端已支持 HKUST(GZ) Campus SSO Authorization Code + PKCE 登录。

需要在 `.env` 中配置：

```env
SSO_DOMAIN=https://devsso.hkust-gz.edu.cn
SSO_CLIENT_ID=你的 client id
SSO_CLIENT_SECRET=你的 client secret
SSO_REDIRECT_URI=https://localhost:8080/signin-oidc
SSO_POST_LOGOUT_REDIRECT_URI=https://localhost:8080/signout-callback
SSO_SCOPE=openid profile
SSO_USER_PERSISTENCE_ENABLED=true
SSO_USER_TABLE=sso_users
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=lax
```

SSO 相关路由：

- `GET /auth/sso/login`
- `GET /signin-oidc`
- `GET|POST /auth/logout`
- `GET /signout-callback`

SSO token 只保存在后端内存会话中，前端通过 HttpOnly Cookie 维持本地登录态。

SSO 登录成功后，后端会将 SSO 返回的用户画像 upsert 到 `sso_users` 表，保存外部身份
`sub` 与本地业务用户的映射，以及 `name/display_name/type/email/department/emp_id`
等业务字段；不会保存用户密码。若 MySQL 不可用或未初始化该表，登录不会被阻断，但后端会记录 warning。

## Harbor 镜像仓库

当前已接入 Harbor 只读查询，用于“工作台”右侧展示镜像：

- “我的镜像”：当前登录用户邮箱对应的私有项目。
- “公有镜像”：`HARBOR_PUBLIC_PROJECT` 指向的 Harbor 项目，当前默认 `dev`。

第一版约束：

- Harbor 用户名继续使用 SSO 用户邮箱。
- 私有项目名按邮箱转换：`user@example.com` -> `user-at-example-dot-com-repo`。
- 不在 SSO 登录时自动创建 Harbor 用户或项目。
- 不开放镜像删除接口。
- 公共镜像项目通过 `HARBOR_PUBLIC_PROJECT` 配置，后续可改为本项目专用公共镜像项目。

需要在 `.env` 中配置：

```env
HARBOR_URL=http://10.120.17.137:5053/api/v2.0/
HARBOR_REGISTRY=gpunion2.io
HARBOR_ADMIN_USERNAME=你的 Harbor 管理员账号
HARBOR_ADMIN_PASSWORD=你的 Harbor 管理员密码
HARBOR_USER_PROJECT_SUFFIX=-repo
HARBOR_PUBLIC_PROJECT=dev
HARBOR_REQUEST_TIMEOUT_SECONDS=10
```

接口：

- `GET /api/v1/harbor/me`：查询当前登录用户邮箱对应的 Harbor 私有项目，以及配置的公有镜像项目。

## K3s Namespace 与开发容器

当前已对接 K3s 的 namespace 创建、默认 devbox Pod 申请、容器删除，以及基于 Traefik Ingress 的
HTTP 应用暴露能力；暂不实现 PVC 等其他服务。

后端不会在 SSO 登录/注册时创建 namespace。用户在工作台点击“申请容器”时，后端才会使用当前
登录用户的 `emp_id` 确保存在对应 namespace：

```text
emp_id = 20260001 -> namespace = 20260001
emp_id = ABC_001 -> namespace = abc-001
```

`emp_id` 在 `sso_users` 表中已配置唯一约束。对于已有数据库，请先确认没有重复的非空
`emp_id`，再执行：

```text
backend/sql/add_unique_sso_emp_id.sql
```

应用名称 `app_name` 会写入 `containers.app_name`，并通过唯一索引保证全局唯一。对于已有数据库，
请执行：

```text
backend/sql/add_unique_containers_app_name.sql
backend/sql/add_ssh_container_fields.sql
```

K3s 连接配置：

```env
KUBECONFIG_PATH=
K3S_CONFIG_PATH=/etc/rancher/k3s/k3s.yaml
K3S_DEVBOX_IMAGE=gpunion2.io/dev/devbox:latest
K3S_DEVBOX_CPU=2
K3S_DEVBOX_MEMORY=4Gi
K3S_DEVBOX_COMMAND=/bin/sh,-c,sleep infinity
K3S_DEVBOX_DNS_NAMESERVERS=10.90.63.2,10.90.63.3,8.8.8.8
K3S_APPS_HOST=gpunion.hkust-gz.edu.cn
K3S_APPS_PATH_PREFIX=/apps
K3S_APPS_PUBLIC_BASE_URL=https://gpunion.hkust-gz.edu.cn/apps
SSH_GATEWAY_ENABLED=true
SSH_GATEWAY_HOST=0.0.0.0
SSH_GATEWAY_PORT=2222
SSH_GATEWAY_PUBLIC_HOST=10.120.17.138
SSH_GATEWAY_HOST_KEY_PATH=
WEBSSH_PUBLIC_PATH_PREFIX=/ssh
```

接口：

- `GET /api/v1/k3s/apps/check-name?app_name=demo`：检查应用名称是否已被使用；应用名称以
  `containers.app_name` 唯一索引作为全局唯一来源，对应访问路径为
  `K3S_APPS_PUBLIC_BASE_URL/{app_name}`。
- `POST /api/v1/k3s/devbox`：在当前登录用户 `emp_id` 对应的 namespace 下创建默认 devbox Pod。
  请求体：

  ```json
  {
    "app_name": "demo",
    "connection_password": "至少 6 位连接密码"
  }
  ```

- `GET /api/v1/k3s/containers`：查询当前登录用户 `emp_id` 对应 namespace 下的 Pod 列表；namespace 不存在时返回空列表。
- `DELETE /api/v1/k3s/containers/{pod_name}`：删除当前登录用户 namespace 下的 Pod，并同步删除对应
  Secret、Web Service、SSH Service、Ingress 和 `containers` 表记录。
- `WebSocket /api/v1/ssh/ws/{app_name}/{ssh_username}`：WebSSH 浏览器终端通道。

说明：

- SSO 登录只负责认证和用户画像落库，不再创建 K3s namespace。
- 如果 namespace 已存在，会直接复用。
- 工作台“申请容器”按钮会先要求填写 `app_name` 和连接密码；后端会再次校验 `app_name` 未被使用。
- 申请容器时会先确认 namespace 存在，不存在则创建，然后创建一个默认 devbox Pod、一个
  Web ClusterIP Service、一个 SSH ClusterIP Service、一个 Traefik Ingress，并将容器内 3000 端口应用暴露为
  `https://gpunion.hkust-gz.edu.cn/apps/{app_name}`。
- 申请成功时会向 `containers` 表写入 `pod_name`、`app_name`、`namespace`、`username`、
  `ssh_username`、`ssh_service_name` 和连接密码；其中
  `app_name` 使用唯一索引避免并发申请时重名。
- 默认 devbox Pod 资源 request/limit 均为 2 核 CPU、4Gi 内存，镜像默认使用 `gpunion2.io/dev/devbox:latest`。
- 默认 devbox Pod 使用 `K3S_DEVBOX_DNS_NAMESERVERS` 配置固定 DNS，并设置 `dnsPolicy=None`，用于绕过
  当前 kube-dns 外部域名解析超时问题；如果该配置留空，则恢复 Kubernetes 默认 `ClusterFirst` DNS。
- devbox 镜像需内置 `openssh-server`、`bash`、`useradd`、`chpasswd`、`ssh-keygen`、`sudo`。
- 连接密码会保存到 Kubernetes Secret 和 `containers.password`，用于 WebSSH 和原生 SSH 登录。
- 当前后端以 systemd 进程运行在宿主机上，不直接依赖宿主机访问 K3s ClusterIP；WebSSH 和原生 SSH
  Gateway 会通过 Kubernetes API 对目标 Pod 建立临时 port-forward，再连接容器内 SSHD。
- WebSSH 地址格式：`https://gpunion.hkust-gz.edu.cn/ssh/{app_name}+{ssh_username}`。
- 第一版原生 SSH 地址格式：`ssh {ssh_username}+{app_name}@10.120.17.138 -p 2222`；如果用户名包含
  `@`、空格等特殊字符，工作台会改用等价的 `ssh -l '{ssh_username}+{app_name}' 10.120.17.138 -p 2222`。
- 建议生产环境设置 `SSH_GATEWAY_HOST_KEY_PATH` 为一个后端进程可读写的固定文件路径，避免后端重启后
  原生 SSH 客户端提示服务端 HostKey 变化。
- 由于应用是按 `/apps/{app_name}` 子路径代理，容器内 Web 应用需要在模板或项目配置中设置对应
  base path，否则页面 HTML 可能能打开但静态资源路径会不正确。
- demo 登录如需测试容器申请，可在 `.env` 中配置 `DEMO_EMP_ID`；MySQL 本地用户则读取 `users.emp_id`。

## 已知限制与后续优化

- 当前后端登录 session 仍由单进程内存 `TokenStore` 保存，适合当前单实例部署；后续如果启用多进程、
  多节点或需要应用重启后保留登录态，应迁移到 Redis / 数据库存储。
- SSO 授权地址中保留 `client_secret` 参数。虽然常规 OAuth2/OIDC 实践通常不建议在 authorize URL 中
  传递 secret，但当前对接文档将其列为必传参数，因此暂不修改；除非 SSO 管理员确认协议变更。
