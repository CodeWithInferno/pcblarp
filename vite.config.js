import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // ChatPCB backend (manay) — pipeline runs + artifact downloads
      '/api': 'http://localhost:8000',
      '/artifacts': 'http://localhost:8000',
    },
  },
})
