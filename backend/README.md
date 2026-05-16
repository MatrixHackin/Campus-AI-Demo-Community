# Backend / FastAPI

## 功能
- 登录接口（支持 demo 模式，保留自定义数据库接口扩展点）
- 校园 SSO 登录
- 当前工作台页面暂为空，后续通过创建 container 的方式重新实现工作台能力

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

## 已知限制与后续优化

- 当前后端登录 session 仍由单进程内存 `TokenStore` 保存，适合当前单实例部署；后续如果启用多进程、
  多节点或需要应用重启后保留登录态，应迁移到 Redis / 数据库存储。
- SSO 授权地址中保留 `client_secret` 参数。虽然常规 OAuth2/OIDC 实践通常不建议在 authorize URL 中
  传递 secret，但当前对接文档将其列为必传参数，因此暂不修改；除非 SSO 管理员确认协议变更。
