import { motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import type { Collection } from '../api/types.ts'
import { shortTitle } from '../lib/format.ts'
import { EASE } from '../lib/motion.ts'
import { MetaLine } from './MetaLine.tsx'
import { StripPosters } from './StripPosters.tsx'

type Props = {
  collection: Collection
  open: boolean
  onToggle: () => void
  // Kart cevap akarken belirdiyse aşağıdan kayarak gelir; geçmiş sohbetlerde doğrudan çizilir.
  animate: boolean
  // Her `collection` olayında artar; değişince kart kısa süre kehribar parlar.
  tick: number
}

export function CollectionCard({ collection, open, onToggle, animate, tick }: Props) {
  const [glow, setGlow] = useState(false)
  const lastTick = useRef(tick)

  useEffect(() => {
    if (tick === lastTick.current) return
    lastTick.current = tick
    setGlow(true)
    const timer = setTimeout(() => setGlow(false), 1400)
    return () => clearTimeout(timer)
  }, [tick])

  const parts = [`${collection.films.length} film`, ...(collection.status === 'approved' ? ['kaydedildi'] : ['taslak', 'onay bekliyor'])]
  return (
    <motion.button
      type="button"
      className={`ccard${glow ? ' glow' : ''}`}
      data-open={open}
      aria-expanded={open}
      onClick={onToggle}
      initial={animate ? { opacity: 0, y: 12 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: EASE }}
    >
      <StripPosters urls={collection.films.slice(0, 6).map((film) => film.poster_url)} />
      <span className="ct">
        <b>{shortTitle(collection.title)}</b>
        <MetaLine parts={parts} />
      </span>
      <span className="go">{open ? 'kapat ›' : 'aç ›'}</span>
    </motion.button>
  )
}
