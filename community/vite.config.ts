import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The community is the main GitHub Pages experience at /hackmate/.
export default defineConfig({
  plugins: [react()],
  base: '/hackmate/',
  build: {
    outDir: '../docs',
    // Preserve stats.json and other independently generated Pages files.
    emptyOutDir: false,
  },
})
