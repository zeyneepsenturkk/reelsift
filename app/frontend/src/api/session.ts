// Oturum ortada düşerse (korumalı bir uç 401 `not_authenticated` dönerse) oturum kapalı sayılır.
let handler: (() => void) | null = null

export function setUnauthorizedHandler(next: (() => void) | null): void {
  handler = next
}

export function notifyUnauthorized(): void {
  handler?.()
}
