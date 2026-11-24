// Sunucunun {detail, code} cevabı ve ağ hataları tek sınıfa çevrilir; bileşenler `detail`ı kullanıcıya göstermez.
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}
