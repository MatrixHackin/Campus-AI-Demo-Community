import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { campusAppsProxy } from './vite-apps-proxy.js'

export default defineConfig({
  plugins: [react(), campusAppsProxy()],
  server: {
    port: 5173,
    host: '0.0.0.0',
    allowedHosts: ['gpunion.hkust-gz.edu.cn'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true
      },
      '/auth': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true
      },
      '/signin-oidc': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true
      },
      '/signout-callback': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true
      },
      '/apps/': {
        target: 'http://127.0.0.1:80',
        changeOrigin: true,
        ws: true,
        configure(proxy) {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('Host', 'gpunion.hkust-gz.edu.cn')
          })
          proxy.on('proxyReqWs', (proxyReq) => {
            proxyReq.setHeader('Host', 'gpunion.hkust-gz.edu.cn')
          })
        }
      },
      '/share/apps': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true
      }
    }
  }
})
