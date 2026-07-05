export const useTelegram = () => {
  const tg = import.meta.client ? (window as any).Telegram?.WebApp : null

  const initData = tg?.initData ?? ''
  const user = tg?.initDataUnsafe?.user ?? null
  const themeParams = tg?.themeParams ?? {}
  const colorScheme = tg?.colorScheme ?? 'dark'
  // The SDK object exists in a plain browser too; real Telegram always provides initData
  const isTelegram = Boolean(initData)

  const ready = () => tg?.ready()
  const expand = () => tg?.expand()

  const setChrome = (color: string) => {
    try {
      tg?.setHeaderColor?.(color)
      tg?.setBackgroundColor?.(color)
      tg?.setBottomBarColor?.(color)
    } catch {}
  }

  const showBackButton = (cb: () => void) => {
    if (!tg) return
    tg.BackButton.show()
    tg.BackButton.onClick(cb)
  }
  const hideBackButton = (cb?: () => void) => {
    if (!tg) return
    if (cb) tg.BackButton.offClick(cb)
    tg.BackButton.hide()
  }

  const haptic = {
    impact: (style: 'light' | 'medium' | 'heavy' = 'light') => {
      try { tg?.HapticFeedback?.impactOccurred(style) } catch {}
    },
    select: () => {
      try { tg?.HapticFeedback?.selectionChanged() } catch {}
    },
    success: () => {
      try { tg?.HapticFeedback?.notificationOccurred('success') } catch {}
    },
    error: () => {
      try { tg?.HapticFeedback?.notificationOccurred('error') } catch {}
    }
  }

  const close = () => tg?.close()
  const showAlert = (msg: string) => tg?.showAlert(msg)

  return {
    tg,
    initData,
    user,
    themeParams,
    colorScheme,
    isTelegram,
    ready,
    expand,
    setChrome,
    showBackButton,
    hideBackButton,
    haptic,
    close,
    showAlert
  }
}
