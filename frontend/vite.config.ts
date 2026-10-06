import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const API_TARGET = 'http://127.0.0.1:4111'
const proxy = { '/api': { target: API_TARGET, changeOrigin: true } }

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 4110, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
  build: { sourcemap: true },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    restoreMocks: true,
  },
})
