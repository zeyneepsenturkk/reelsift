// localStorage özel pencerede ya da engelliyken hata verebilir; arayüz onsuz da çalışmalı.
export function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // Tercih kaydedilemedi; oturum boyunca bellekteki değer geçerli.
  }
}
