export const formatMoney = (value: number, digits = 0): string =>
  new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits
  }).format(value ?? 0)

export const formatMoneyShort = (value: number): string => {
  const v = value ?? 0
  if (v >= 1000) {
    const k = v / 1000
    return `${k >= 10 ? Math.round(k) : Math.round(k * 10) / 10}к`
  }
  return String(Math.round(v))
}

export const formatHoursShort = (h: number): string => {
  const total = Math.round((h ?? 0) * 60)
  const hours = Math.floor(total / 60)
  const mins = total % 60
  if (!total) return ''
  if (hours === 0) return `${mins}м`
  return mins > 0 ? `${hours}ч${mins}м` : `${hours}ч`
}

export const formatHoursLabel = (h: number): string => {
  const total = Math.round((h ?? 0) * 60)
  const hours = Math.floor(total / 60)
  const mins = total % 60
  if (hours === 0 && mins === 0) return '0ч'
  return mins > 0 ? `${hours}ч ${mins}м` : `${hours}ч`
}

export const formatElapsed = (ms: number): string => {
  const h = Math.floor(ms / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export const formatDayLabel = (dateStr: string): string => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', weekday: 'short' })
}
