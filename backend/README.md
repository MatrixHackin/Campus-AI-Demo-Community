# Backend / FastAPI

## 功能
- 登录接口（支持 demo 模式，保留自定义数据库接口扩展点）
- 开发沙盒接口（可通过 Kubernetes API 申请 Pod）
- 开发沙盒接口直接连接真实 K3s 集群创建 Pod

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

## 开发沙盒接口
- `POST /api/v1/sandboxes`
- `GET /api/v1/sandboxes/me`

默认创建的是 Pod，由 K3s scheduler 自动调度；你也可以继续扩展为 Deployment / Service / Ingress。
