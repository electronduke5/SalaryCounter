<template>
  <div class="page">
    <AppHeader kicker="Отчёты" title="Заработок" />

    <SegmentedControl v-model="activePeriod" :options="periods" class="reveal mb-4" />

    <template v-if="loading">
      <SkeletonBlock height="9rem" radius="1.375rem" class="mb-4" />
      <div class="space-y-2">
        <SkeletonBlock v-for="i in 4" :key="i" height="4rem" radius="1.375rem" />
      </div>
    </template>

    <div v-else-if="error" class="card reveal border-red-500/25 bg-red-500/8 p-4">
      <p class="text-sm font-semibold text-red-300">{{ error }}</p>
    </div>

    <template v-else>
      <HeroEarnings
        class="reveal"
        :amount="data.total_earnings"
        :hours="data.total_hours"
        :label="`Итого · ${activePeriodLabel}`"
      >
        <div v-if="previous" class="flex items-center gap-2 text-sm">
          <DeltaBadge :pct="earningsDelta" :has-current="data.total_earnings > 0" />
          <span class="text-[13px] font-semibold text-mist">vs {{ previous.label }}</span>
        </div>
      </HeroEarnings>

      <!-- Comparison with previous period: paired horizontal bars -->
      <section v-if="previous" class="reveal mb-4 space-y-2" style="animation-delay: 40ms">
        <div v-for="m in compareBars" :key="m.title" class="card space-y-3 px-4 py-3.5">
          <div class="flex items-center justify-between">
            <span class="text-[13px] font-semibold text-mist">{{ m.title }}</span>
            <DeltaBadge :pct="m.pct" :has-current="m.cur > 0" class="text-xs" />
          </div>
          <div v-for="bar in m.bars" :key="bar.name">
            <div class="mb-1 flex items-baseline justify-between gap-2 text-[11px]">
              <span class="truncate font-semibold" :class="bar.current ? 'text-ink' : 'text-mist'">
                {{ bar.name }}
              </span>
              <span
                class="shrink-0 font-bold tabular-nums"
                :class="bar.current ? 'text-ink' : 'text-mist'"
              >
                {{ bar.label }}
              </span>
            </div>
            <div class="h-2 overflow-hidden rounded-full bg-surface-2">
              <div
                class="h-full rounded-full transition-all duration-500"
                :class="bar.current ? 'bg-acid' : 'bg-mist/40'"
                :style="{ width: `${bar.width}%` }"
              />
            </div>
          </div>
        </div>
      </section>

      <!-- Breakdown chart: current vs previous period -->
      <section v-if="chartSeries.labels.length" class="reveal" style="animation-delay: 80ms">
        <h2 class="mb-2.5 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">
          {{ activePeriod === 'year' ? 'По месяцам' : 'По дням' }}
        </h2>
        <LineChart
          :labels="chartSeries.labels"
          :current="chartSeries.current"
          :previous="chartSeries.previous"
          :current-label="activePeriodLabel"
          :previous-label="previous?.label"
        />
      </section>

      <EmptyState
        v-else-if="!data.total_hours"
        class="reveal"
        style="animation-delay: 80ms"
        icon="i-lucide-calendar-off"
        title="Нет данных за этот период"
        hint="Записи появятся после трекинга времени"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
const api = useApi()

const periods = [
  { value: 'today', label: 'Сегодня' },
  { value: 'yesterday', label: 'Вчера' },
  { value: 'week', label: 'Неделя' },
  { value: 'month', label: 'Месяц' },
  { value: 'year', label: 'Год' }
]

const activePeriod = ref('week')
const loading = ref(true)
const error = ref<string | null>(null)
const data = ref<any>({ total_hours: 0, total_earnings: 0 })

const activePeriodLabel = computed(
  () => periods.find(p => p.value === activePeriod.value)?.label ?? ''
)

const previous = computed(() => data.value.previous ?? null)

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
const monthNum = (ym: string) => parseInt(ym.split('-')[1] ?? '0', 10)

type ChartPoint = { hours: number; earnings: number } | null
const pt = (h: number, e: number): ChartPoint => ({ hours: h ?? 0, earnings: e ?? 0 })

// Aligns the current period and the previous one onto a shared x-axis so the
// chart can draw two comparable lines. Year → by month number (data has gaps);
// week/month → by day index (both series are gap-free from the period start).
const chartSeries = computed<{
  labels: string[]
  current: ChartPoint[]
  previous: ChartPoint[]
}>(() => {
  const p = previous.value
  if (activePeriod.value === 'year') {
    const cur = new Map<number, ChartPoint>()
    ;(data.value.months ?? []).forEach((m: any) => cur.set(monthNum(m.month), pt(m.total_hours, m.total_earnings)))
    const prev = new Map<number, ChartPoint>()
    ;(p?.series ?? []).forEach((m: any) => prev.set(monthNum(m.month), pt(m.total_hours, m.total_earnings)))
    return {
      labels: MONTHS_SHORT,
      current: MONTHS_SHORT.map((_, i) => cur.get(i + 1) ?? null),
      previous: MONTHS_SHORT.map((_, i) => prev.get(i + 1) ?? null)
    }
  }
  const cur = data.value.days ?? []
  const prev = p?.series ?? []
  const len = Math.max(cur.length, prev.length)
  const weekly = activePeriod.value === 'week'
  return {
    labels: Array.from({ length: len }, (_, i) => (weekly ? WEEKDAYS[i] ?? '' : String(i + 1))),
    current: Array.from({ length: len }, (_, i) => (cur[i] ? pt(cur[i].total_hours, cur[i].total_earnings) : null)),
    previous: Array.from({ length: len }, (_, i) => (prev[i] ? pt(prev[i].total_hours, prev[i].total_earnings) : null))
  }
})

const pctChange = (cur: number, prev: number): number | null =>
  prev ? ((cur - prev) / prev) * 100 : null

const earningsDelta = computed(() =>
  pctChange(data.value.total_earnings ?? 0, previous.value?.total_earnings ?? 0)
)

// Two paired horizontal bars per metric: current period vs previous, lengths
// scaled to the larger of the two so the comparison reads at a glance.
const compareBars = computed(() => {
  const p = previous.value
  if (!p) return []
  const metric = (title: string, cur: number, prev: number, fmt: (v: number) => string) => {
    const max = Math.max(cur, prev, 0.01)
    return {
      title,
      cur,
      pct: pctChange(cur, prev),
      bars: [
        { name: activePeriodLabel.value, current: true, label: fmt(cur), width: (cur / max) * 100 },
        { name: p.label, current: false, label: fmt(prev), width: (prev / max) * 100 }
      ]
    }
  }
  return [
    metric('Заработок', data.value.total_earnings ?? 0, p.total_earnings ?? 0, v => `${formatMoney(v)} ₽`),
    metric('Часы', data.value.total_hours ?? 0, p.total_hours ?? 0, formatHoursLabel)
  ]
})

const loadData = async (period: string) => {
  loading.value = true
  error.value = null
  try {
    data.value = await api.get(`/earnings/${period}`)
  } catch (e: any) {
    error.value = e.message
    data.value = { total_hours: 0, total_earnings: 0 }
  } finally {
    loading.value = false
  }
}

watch(activePeriod, loadData)
onMounted(() => loadData(activePeriod.value))
</script>
