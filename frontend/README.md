# Frontend / React

## 功能
- 炫酷首页
- 登录页面
- 登录后主控台
- 调用 FastAPI 后端申请开发沙盒

## 代码导读
- 前端专用导读：`FRONTEND_GUIDE.md`

## 启动
```bash
npm install
npm run dev
```

## 环境变量
如需覆盖默认 API 地址，可创建 `.env`：
```bash
VITE_API_BASE_URL=http://192.168.1.10:8000/api/v1
```

如果不配置 `VITE_API_BASE_URL`，前端会自动请求 `http://当前访问主机名:8000/api/v1`。

## 局域网访问
- Vite 已监听 `0.0.0.0:5173`
- 局域网内其他设备可通过 `http://你的电脑局域网IP:5173` 访问
- 请同时确保后端启动在 `0.0.0.0:8000`
