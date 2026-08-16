import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages serves this repo at https://riftaway7-code.github.io/hackmate/
// and the community app is built into docs/community/, so it's reachable at
// https://riftaway7-code.github.io/hackmate/community/
export default defineConfig({
  plugins: [react()],
  base: '/hackmate/community/',
  build: {
    outDir: '../docs/community',
    emptyOutDir: true,
  },
})
