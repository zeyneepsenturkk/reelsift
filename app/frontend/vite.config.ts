import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Arayüz ve API aynı origin'den görünsün diye /api arka uca vekil edilir (CORS gerekmesin).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Birim testleri yalnız saf mantığı sınar (akış ayrıştırıcı, indirgeyici, biçimleyiciler); DOM gerekmez.
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Windows bind mount'ta dosya olayları gelmediği için yoklama.
    watch: { usePolling: true },
    proxy: {
      '/api': process.env.VITE_API_PROXY ?? 'http://localhost:8000',
    },
  },
})
