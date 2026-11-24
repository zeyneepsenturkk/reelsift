import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { ChatInput } from '../components/ChatInput.tsx'
import { IDEA_POOL, pickIdeas } from '../lib/ideas.ts'
import { useSessionActions } from '../state/sessions.tsx'
import { useShell } from '../state/shell.tsx'

export default function NewChatPage() {
  const { startChat } = useSessionActions()
  const { setPanel } = useShell()
  const navigate = useNavigate()
  const [failed, setFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  // Sayfa her bağlandığında yeniden seçilir; açıkken değişmez.
  const [ideas] = useState(() => pickIdeas(IDEA_POOL, 3))

  useEffect(() => setPanel('closed'), [setPanel])

  // Önce sohbet oluşur, sonra `/s/:id`ye geçilir; akış oturum katmanında sürdüğü için geçişte kopmaz.
  const begin = async (text: string): Promise<boolean> => {
    setFailed(false)
    setBusy(true)
    try {
      const chatId = await startChat(text)
      navigate(`/s/${chatId}`)
      return true
    } catch {
      setFailed(true)
      setBusy(false)
      return false
    }
  }

  return (
    <>
      <main className="chat solo">
        <div className="empty">
          <h1>Bugün nasıl bir seçki hazırlıyoruz?</h1>
          <p>Aklındaki temayı, dönemi ya da havayı anlat; arşivi senin için tarayayım.</p>
          <ChatInput placeholder="Örn. karlı kasabalarda geçen, ağır tempolu polisiyeler…" onSend={begin} autoFocus />
          {failed && (
            <p className="form-error" role="alert">
              Sohbet açılamadı, bir daha dener misin?
            </p>
          )}
          <div className="ideas">
            {ideas.map((idea) => (
              <button key={idea.tag} className="idea" disabled={busy} onClick={() => void begin(idea.text)}>
                <span className="label">{idea.tag}</span>
                {idea.text}
              </button>
            ))}
          </div>
        </div>
      </main>
      {/* Boş panel yuvası: taslaktaki 1 px kesik çizgili kenar sütun genişliğine dahil, yerleşim sohbet ekranıyla aynı kalsın. */}
      <section className="draft" aria-hidden="true" />
    </>
  )
}
