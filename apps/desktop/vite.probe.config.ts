import { resolve } from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
export default defineConfig({
  root: resolve(__dirname, 'src/renderer'),
  resolve: { alias: { '@renderer': resolve(__dirname, 'src/renderer/src') } },
  plugins: [react()], server: { port: 5179 }
})
