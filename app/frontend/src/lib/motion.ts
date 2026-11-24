// Taslaktaki --ease eğrisi (cubic-bezier(.2,.7,.2,1)); index.css'teki --ease-reel ile aynı.
export const EASE = [0.2, 0.7, 0.2, 1] as const

// Liste öğeleri ilk çizimde 30 ms arayla sırayla belirir; 12'den sonrakiler birlikte.
export function staggerDelay(index: number): number {
  return Math.min(index, 11) * 0.03
}
