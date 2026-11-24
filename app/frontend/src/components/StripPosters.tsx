// Koleksiyon kartının üst üste binen afiş şeridi. Afişi olmayan ya da yüklenemeyen yer sade zemin olarak kalır.
export function StripPosters({ urls }: { urls: (string | null)[] }) {
  return (
    <span className="strip" aria-hidden="true">
      {urls.map((url, index) =>
        url ? (
          <img
            key={`${index}-${url}`}
            src={url}
            alt=""
            loading="lazy"
            decoding="async"
            onError={(event) => event.currentTarget.setAttribute('data-broken', '')}
          />
        ) : (
          <span className="ph" key={index} />
        ),
      )}
    </span>
  )
}
