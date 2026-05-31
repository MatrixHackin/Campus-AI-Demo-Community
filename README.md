# Campus AI Demo Community

一个面向开发沙盒申请、SSH/WebSSH 开发和应用发布的前后端分离平台：

- **前端**：React + Vite
- **后端**：FastAPI
- **云原生能力**：后端通过 Kubernetes API 申请开发沙盒容器

## 页面功能
- 首页
- 登录页面
- 开发沙盒申请和镜像保存
- SSH / WebSSH 开发连接
- 应用市场发布、审核和通知

## 目录结构
```text
backend/   FastAPI 控制面、SSH Gateway 镜像源码和数据库脚本
frontend/  React 前端
deploy/    k3s、systemd、TCP proxy 和压测配置
```

## 代码导读
- 后端部署、配置和接口说明见：`backend/README.md`
- 前端代码导读见：`frontend/FRONTEND_GUIDE.md`

## 快速启动
### 1. 启动后端
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. 启动前端
```bash
cd frontend
npm install
npm run dev
```

## 局域网访问
- 前端默认监听 `0.0.0.0:5173`
- 后端默认监听 `0.0.0.0:8000`
- 前端若未配置 `VITE_API_BASE_URL`，会自动请求 `http://当前访问主机名:8000/api/v1`
- 局域网内其他设备可通过 `http://你的电脑局域网IP:5173` 打开页面
- 可先访问 `http://你的电脑局域网IP:8000/api/health` 检查后端连通性

## 演示账号
- 用户名：`admin`
- 密码：`admin123`

## 数据库认证接口预留位置
- `backend/app/db/interfaces.py`
- `backend/app/services/auth_service.py`

## Kubernetes 沙盒逻辑位置
- `backend/app/services/k3s_service.py`

沙盒接口连接真实 K3s 集群创建 Pod，由 K3s scheduler 调度到 `competition=true` 节点。
