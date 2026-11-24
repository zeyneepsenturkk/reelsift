import type { CollectionFilm } from '../api/types.ts'
import { creditRows, detailSubline } from '../lib/format.ts'

type Props = {
  film: CollectionFilm
  // Verilirse "Bunun yerine başkasını bul" düğmesi çıkar (yalnız taslakta).
  onReplace?: (film: CollectionFilm) => void
}

// Gerekçe (Türkçe, bizim yazdığımız) ile kaynak alıntısı (birebir, çevrilmeden) ayrı görünür.
export function FilmDetail({ film, onReplace }: Props) {
  const credits = creditRows(film)
  return (
    <div className="detail">
      <div>
        <h3>
          {film.title_tr || film.title} {film.title_tr && <em>· {film.title}</em>}
        </h3>
        <div className="sub label">{detailSubline(film)}</div>
        {credits.length > 0 && (
          <dl className="credits">
            {credits.map((row) => (
              <div key={row.label} className="credit-row">
                <dt className="label">{row.label}</dt>
                <dd>{row.names}</dd>
              </div>
            ))}
          </dl>
        )}
        <div className="label gap">neden seçildi</div>
        <p>{film.rationale}</p>
        {onReplace && (
          <div className="btn-row">
            <button className="btn" onClick={() => onReplace(film)}>
              Bunun yerine başkasını bul
            </button>
          </div>
        )}
      </div>
      <div>
        <div className="label gap-lg">dayandığı kaynak</div>
        {film.source_quote && <div className="quote">“{film.source_quote}”</div>}
        {film.source_quote && film.quote_source && (
          <div className="quote-src">
            <span className="label">alıntı:</span>
            {film.quote_source.url ? (
              <a href={film.quote_source.url} target="_blank" rel="noopener noreferrer">
                {film.quote_source.label}
              </a>
            ) : (
              <span className="quote-src-text">{film.quote_source.label}</span>
            )}
          </div>
        )}
        {film.sources.length > 0 && (
          <div className="src">
            {film.sources.map((source) => (
              <a key={source.kind} href={source.url} target="_blank" rel="noopener noreferrer">
                {source.label}
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
