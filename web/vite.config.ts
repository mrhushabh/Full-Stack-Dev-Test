import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxying /api to the FastAPI process keeps the browser on a single origin,
    // so the app uses relative URLs and there is no API base URL to configure or
    // get wrong. CORS stays configured on the server for anyone who prefers to
    // run the two independently.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
