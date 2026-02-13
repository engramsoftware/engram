import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    // Bind to 0.0.0.0 so LAN/VPN devices can access the frontend
    host: '0.0.0.0',
    proxy: {
      '/api': {
        // Backend now serves all API routes under /api — no rewrite needed
        target: process.env.BACKEND_URL || 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
