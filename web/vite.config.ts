import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 개발 서버(npm run dev, 5173)는 백엔드 API 경로를 8000 으로 넘긴다. 브라우저 입장에서는 같은 오리진이라
// 쿠키 세션과 백엔드의 Origin 검사(src/auth/origin.py)가 그대로 동작한다. 백엔드 주소는 BACKEND_URL 로 바꾼다.
const backend = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

// /community 자체는 React 화면 경로라 프록시하지 않고, API 하위 경로(/community/posts 등)만 넘긴다.
// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(['/auth', '/session', '/lists', '/reviews', '/health', '/pc', '/catalog', '/peripherals/interpret', '/peripherals/catalog', '/community/posts', '/community/comments', '/community/search', '/community/uploads', '/community/images'].map(path => [path, backend])),
  },
})
