import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Same-origin in dev, so no CORS surprises when the extension talks to it later.
      // Override with API_PORT when 8000 is occupied — on Windows a killed uvicorn
      // can leave the port bound to a PID that no longer exists.
      '/api': {
        target: `http://127.0.0.1:${process.env.API_PORT ?? 8011}`,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})
