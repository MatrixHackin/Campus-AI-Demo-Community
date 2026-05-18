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

## 本地分配账号与 MySQL 登录

已内置 MySQL 登录认证仓库，可在 DataGrip 中执行：

```text
sql/mysql_auth.sql
```

普通本地账号和 SSO 用户统一保存在 `sso_users` 表。区别仅在于：

- `auth_provider='sso'`：通过校园 SSO 登录，`provider_subject` 为 SSO `sub`。
- `auth_provider='local'`：由管理员分配，使用用户名和密码登录，`provider_subject` 为 `local:{email}`。

然后在 `.env` 中配置本地登录使用 MySQL：

```env
AUTH_BACKEND=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=campusai
MYSQL_PASSWORD=你的密码
MYSQL_DATABASE=campus_ai
SSO_USER_TABLE=sso_users
```

已有数据库请先执行：

```text
backend/sql/add_local_login_to_sso_users.sql
```

创建管理员分配账号可使用脚本：

```bash
cd backend
python scripts/create_local_user.py \
  --email user@example.com \
  --username devuser01 \
  --emp-id gzlocal001 \
  --display-name "Dev User 01"
```

脚本会检查 `provider_subject / username / email / emp_id` 是否和现有用户冲突；未传
`--password` 时会自动生成初始密码。本地账号必须配置 `email + username + emp_id`，才能完整使用
工作台、Harbor、容器、WebSSH、应用发布等功能。

分配后用户登录时使用 `--username` 对应的用户名和初始密码；`email` 主要用于 Harbor 私有镜像仓库。

## 校园 SSO 登录

后端已支持 HKUST(GZ) Campus SSO Authorization Code + PKCE 登录。

需要在 `.env` 中配置：

```env
SSO_DOMAIN=https://sso.hkust-gz.edu.cn
SSO_CLIENT_ID=gpunion.client
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
等业务字段；SSO 用户不会保存密码。若 MySQL 不可用或未初始化该表，登录不会被阻断，但后端会记录 warning。

## Harbor 镜像仓库

当前已接入 Harbor，用于“工作台”右侧展示镜像，并在用户点击“保存容器”时为用户准备私有仓库：

- “我的镜像”：当前登录用户邮箱对应的私有项目。
- “公有镜像”：`HARBOR_PUBLIC_PROJECT` 指向的 Harbor 项目，当前默认 `dev`。

- Harbor 用户名使用当前登录用户邮箱。
- 私有项目名按邮箱转换：`user@example.com` -> `user-at-example-dot-com-repo`。
- 不在 SSO 登录或首次申请容器时自动创建 Harbor 用户或项目；用户点击“保存容器”时，会自动确保 Harbor 用户、
  private 项目和项目 developer 成员关系存在。
- 保存容器时，会在用户 namespace 中创建/更新 `kubernetes.io/dockerconfigjson` 类型的 imagePullSecret，
  供后续从用户私有项目 pull 镜像使用；保存 Job 也运行在用户 namespace 中并复用该 imagePullSecret 拉取
  `nerdctl` runner 镜像。
- 保存容器时，还会在用户 namespace 中创建/更新一个持久的 Harbor 凭据 Secret，用于 Job 注入
  `HARBOR_USERNAME` / `HARBOR_PASSWORD` 并执行 `nerdctl login` 后 push 镜像；不再为每个 Job 创建临时凭据 Secret。
- 不开放镜像删除接口。
- 公共镜像项目通过 `HARBOR_PUBLIC_PROJECT` 配置，后续可改为本项目专用公共镜像项目。

需要在 `.env` 中配置：

```env
HARBOR_URL=http://10.120.17.137:5053/api/v2.0/
HARBOR_REGISTRY=gpunion2.io
HARBOR_ADMIN_USERNAME=你的 Harbor 管理员账号
HARBOR_ADMIN_PASSWORD=你的 Harbor 管理员密码
HARBOR_USER_DEFAULT_PASSWORD=Habor!123
HARBOR_USER_DEFAULT_STORAGE_QUOTA=53687091200
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
backend/sql/update_log_usage_metrics.sql
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
SSH_GATEWAY_HOST_KEY_PATH=.run/ssh_gateway_host_key
WEBSSH_PUBLIC_PATH_PREFIX=/ssh
PUBLISHED_COVER_STORAGE_DIR=static/covers
PUBLISHED_COVER_PUBLIC_PREFIX=/api/static/covers
PUBLISHED_COVER_MAX_BYTES=1048576
PROMETHEUS_URL=http://10.43.146.195:9090
PROMETHEUS_QUERY_TIMEOUT_SECONDS=5
PROMETHEUS_RETENTION_SECONDS=864000
PROMETHEUS_QUERY_RANGE_MAX_POINTS=240
PROMETHEUS_QUERY_RANGE_MIN_STEP_SECONDS=60
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
- `POST /api/v1/k3s/containers/{pod_name}/commit`：手动保存当前用户容器为 Harbor 私有镜像；请求体为
  `{"image_name":"my-backup-v1"}`。后端会在原 Pod 所在节点创建特权 Job，挂载 K3s containerd socket，
  使用当前用户邮箱和 `HARBOR_USER_DEFAULT_PASSWORD` 执行 `nerdctl login`，再通过 `nerdctl commit`
  生成镜像并推送到当前用户邮箱对应的 Harbor 私有项目。注意：`HARBOR_REGISTRY`
  通常用于展示镜像名，如 `gpunion2.io`；保存容器时的实际 push registry 默认从 `HARBOR_URL` 提取，
  例如 `http://10.120.17.137:5053/api/v2.0/` 会使用 `10.120.17.137:5053`，避免 Job 内访问
  `https://gpunion2.io/v2/` 导致 DNS/协议失败。必要时可用 `K3S_COMMIT_PUSH_REGISTRY` 显式覆盖。
- `GET /api/v1/k3s/jobs/{job_name}`：查询“保存容器”Job 状态。
- `WebSocket /api/v1/ssh/ws/{app_name}/{ssh_username}`：WebSSH 浏览器终端通道。
- `GET /api/v1/community/apps`：应用市场列表。
- `POST /api/v1/community/apps/{pod_name}/publish`：发布当前用户容器到应用市场，表单字段为
  `app_description` 和可选 `cover`；`app_description` 是应用卡片两行内展示的应用简述，最多 40 个字符；
  前端会先压缩封面，后端再限制文件大小。
- `POST /api/v1/community/apps/{publication_id}/visit`：应用市场访问计数；点击“访问应用”时调用并累加
  `published_apps.visit_count`。
- `POST /api/v1/community/apps/{publication_id}/like`：点赞或取消点赞。
- `GET /api/v1/community/apps/{publication_id}/reviews`：查询应用最近评价和当前用户评价。
- `POST /api/v1/community/apps/{publication_id}/review`：提交或更新当前用户评分评论，评分范围 0-5，
  评论最多 240 个字符。
- `DELETE /api/v1/community/apps/{publication_id}/review`：删除当前用户评价。
- `DELETE /api/v1/community/apps/{pod_name}/publish`：取消发布当前用户应用。

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
- 后端默认使用 `.run/ssh_gateway_host_key` 作为固定 SSH Gateway HostKey；请不要删除该文件，否则
  原生 SSH、VS Code Remote-SSH 和 Cursor Remote-SSH 客户端会提示服务端 HostKey 变化。
- 由于应用是按 `/apps/{app_name}` 子路径代理，容器内 Web 应用需要在模板或项目配置中设置对应
  base path，否则页面 HTML 可能能打开但静态资源路径会不正确。
- 应用市场封面第一版保存在后端本地 `PUBLISHED_COVER_STORAGE_DIR`，数据库只保存 URL；如果后续图片量变大，
  建议替换为图床或对象存储，并只在 `published_apps.cover_url` 中保存外部 URL。
- “保存容器”依赖 `K3S_COMMIT_NERDCTL_IMAGE` 内置 `nerdctl`，并要求后端配置 Harbor 管理员账号；该功能会创建
  privileged Job 并挂载宿主机 containerd socket，因此只允许容器所有者通过后端鉴权后触发。保存 Job 设置
  `backoffLimit=0`，失败时不自动重试，避免一个保存任务产生多个 commit Pod 或重复 push。
- 容器资源消耗汇总使用 Prometheus 查询窗口增量：CPU 使用 `increase(container_cpu_usage_seconds_total)` 记录
  core-seconds；网络使用 `increase(container_network_*_bytes_total)` 记录总字节；内存使用
  `container_memory_working_set_bytes` 的窗口平均/峰值，并计算 GB-hours。当前集群 Prometheus retention 为
  10 天，因此提供脚本 `backend/scripts/collect_container_usage.py` 供每周六 23:59 由 cron/systemd timer
  触发，定期把运行中 Pod 资源消耗累加到 `log` 表；删除容器时会在删除 K3s 资源前再汇总最后一个窗口并
  标记 `status=deleted`。如果统计窗口起点早于 Prometheus retention，会写入 `metrics_complete=false`。
- demo 登录如需测试容器申请，可在 `.env` 中配置 `DEMO_EMP_ID`；MySQL 本地分配账号则读取
  `sso_users.emp_id` 和 `sso_users.email`。

每周六 23:59 的 crontab 示例：

```cron
59 23 * * 6 cd /home/ldaphome/liuhemu/document/Campus-AI-Demo-Community/backend && mkdir -p logs && /home/ldaphome/liuhemu/miniconda3/envs/campusai/bin/python scripts/collect_container_usage.py >> logs/container_usage_collect.log 2>&1
```

## 已知限制与后续优化

- 当前后端登录 session 仍由单进程内存 `TokenStore` 保存，适合当前单实例部署；后续如果启用多进程、
  多节点或需要应用重启后保留登录态，应迁移到 Redis / 数据库存储。
- SSO 授权地址中保留 `client_secret` 参数。虽然常规 OAuth2/OIDC 实践通常不建议在 authorize URL 中
  传递 secret，但当前对接文档将其列为必传参数，因此暂不修改；除非 SSO 管理员确认协议变更。
