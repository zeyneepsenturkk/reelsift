// Tek öğeli bildirimin saf durumu. `owner` bildirimin ait olduğu şeyi (ör. `collection:7`) tutar:
// ekrandan giden şey yalnız kendi bildirimini kapatır, ilgisiz bildirim (giriş, ağ hatası) açık kalır.
export type ToastState = { message: string; owner: string | null; visible: boolean }

export const initialToast: ToastState = { message: '', owner: null, visible: false }

export type ToastAction =
  | { type: 'show'; message: string; owner: string | null }
  | { type: 'hide' }
  | { type: 'clear'; owner: string }

export function toastReducer(state: ToastState, action: ToastAction): ToastState {
  switch (action.type) {
    case 'show':
      return { message: action.message, owner: action.owner, visible: true }
    case 'hide':
      return state.visible ? { ...state, visible: false } : state
    case 'clear':
      return state.visible && state.owner === action.owner ? { ...state, visible: false } : state
  }
}
