import { MotionConfig } from 'motion/react'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router'
import { Sidebar } from './components/Sidebar.tsx'
import ChatPage from './pages/ChatPage.tsx'
import CollectionPage from './pages/CollectionPage.tsx'
import CollectionsPage from './pages/CollectionsPage.tsx'
import LoginPage from './pages/LoginPage.tsx'
import NewChatPage from './pages/NewChatPage.tsx'
import SharePage from './pages/SharePage.tsx'
import { AuthProvider, useAuth } from './state/auth.tsx'
import { ListsProvider } from './state/lists.tsx'
import { SessionsProvider } from './state/sessions.tsx'
import { ShellProvider, useShell } from './state/shell.tsx'

// Kenar çubuğu | sohbet | taslak paneli: üç sütunlu ızgara; sütun genişlikleri `data-` özniteliklerinden CSS ile gelir.
function Shell() {
  const { slim, panel, compact } = useShell()
  // Tam ekranda ve dar pencerede panel açıkken kenar çubuğu 64 px çizilir; tercih (slim) değişmez.
  const narrowed = slim || panel === 'full' || (panel === 'open' && compact)
  return (
    <div className="app" data-slim={narrowed} data-panel={panel}>
      <Sidebar />
      <Outlet />
    </div>
  )
}

function RequireAuth() {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <div className="login" aria-busy="true" />
  if (status === 'anon') return <Navigate to="/giris" replace state={{ from: location.pathname }} />
  return (
    <ListsProvider>
      <SessionsProvider>
        <ShellProvider>
          <Shell />
        </ShellProvider>
      </SessionsProvider>
    </ListsProvider>
  )
}

// Oturum bilgisi yalnız giriş gerektiren ve giriş ekranı için istenir: girişsiz paylaşım sayfası `me` çağırmaz.
function AuthLayout() {
  return (
    <AuthProvider>
      <Outlet />
    </AuthProvider>
  )
}

export default function App() {
  return (
    // Sistemde "hareketi azalt" açıksa Motion hareketleri kapanır (CSS tarafı index.css'te).
    <MotionConfig reducedMotion="user">
      <Routes>
        <Route path="/k/:token" element={<SharePage />} />
        <Route element={<AuthLayout />}>
          <Route path="/giris" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
            <Route path="/" element={<NewChatPage />} />
            <Route path="/s/:chatId" element={<ChatPage />} />
            <Route path="/koleksiyonlar" element={<CollectionsPage />} />
            <Route path="/koleksiyon/:id" element={<CollectionPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </MotionConfig>
  )
}
