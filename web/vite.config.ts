import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 5183 is PhotonVox's dev port: the sister products' dev servers use 5175 and 5180-5182, so none collide.
export default defineConfig({
  plugins: [react()],
  server: { port: 5183, strictPort: true, host: true },
})
