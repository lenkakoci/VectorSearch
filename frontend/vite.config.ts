import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The page talks to the API at the relative path /api. In development Vite
// proxies it to the FastAPI process; in Docker nginx does the same, so the
// built page needs no runtime configuration.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8010',
        changeOrigin: true,
      },
    },
  },
})
