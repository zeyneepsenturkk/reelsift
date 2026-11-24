import { useEffect, useRef, useState } from 'react'
import type { CollectionFilm } from '../api/types.ts'
import { filmName } from '../lib/collection.ts'

// Sabit oranlı kutuda afiş; yüklenirken kutu zemini (iskelet) görünür, yoksa/yüklenemezse film adı yazılı kutu çıkar.
export function Poster({ film }: { film: CollectionFilm }) {
  const [failed, setFailed] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const image = useRef<HTMLImageElement>(null)
  const name = filmName(film)

  // Önbellekten gelen görsel onLoad'dan önce tamamlanmış olabilir.
  useEffect(() => {
    const el = image.current
    if (el?.complete) {
      if (el.naturalWidth > 0) setLoaded(true)
      else setFailed(true)
    }
  }, [film.poster_url])

  if (!film.poster_url || failed) return <span className="poster-fallback">{name}</span>
  return (
    <img
      ref={image}
      loading="lazy"
      decoding="async"
      src={film.poster_url}
      alt={`${name} afişi`}
      data-loaded={loaded}
      onLoad={() => setLoaded(true)}
      onError={() => setFailed(true)}
    />
  )
}
