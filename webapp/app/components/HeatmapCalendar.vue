<template>
  <section class="card p-5">
    <div class="mb-4 flex items-center justify-between">
      <h2 class="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">
        <UIcon name="i-lucide-calendar-days" class="size-4" />
        Активность {{ year }}
      </h2>
      <span v-if="selected" class="text-xs font-semibold text-ink">
        {{ formatDayLabel(selected.date) }} · {{ formatHoursLabel(selected.hours) }} ·
        <span class="text-acid">{{ formatMoney(selected.earnings) }} ₽</span>
      </span>
    </div>

    <div ref="scroller" class="no-scrollbar -mx-5 overflow-x-auto px-5">
      <div class="w-max">
        <div class="mb-1 flex gap-[3px] text-[9px] font-bold text-mist">
          <span
            v-for="m in monthLabels"
            :key="m.label + m.offset"
            class="shrink-0"
            :style="{ width: `${m.weeks * 13 - 3}px` }"
          >
            {{ m.label }}
          </span>
        </div>
        <div class="grid grid-flow-col grid-rows-7 gap-[3px]">
          <button
            v-for="cell in cells"
            :key="cell.key"
            class="size-2.5 rounded-[3px] transition-transform active:scale-125"
            :class="cell.cls"
            @click="cell.day && select(cell.day)"
          />
        </div>
      </div>
    </div>

    <div class="mt-3 flex items-center justify-end gap-1.5 text-[10px] font-bold text-mist">
      Меньше
      <span v-for="l in 5" :key="l" class="size-2.5 rounded-[3px]" :class="levelClass(l - 1)" />
      Больше
    </div>
  </section>
</template>

<script setup lang="ts">
export interface HeatmapDay {
  date: string
  hours: number
  earnings: number
  level: number
}

const props = defineProps<{ year: number; days: HeatmapDay[] }>()
const { haptic } = useTelegram()

const scroller = ref<HTMLElement | null>(null)
const selected = ref<HeatmapDay | null>(null)

const select = (day: HeatmapDay) => {
  selected.value = day
  haptic.select()
}

const levelClass = (level: number) =>
  ['bg-surface-2', 'bg-acid/25', 'bg-acid/50', 'bg-acid/75', 'bg-acid'][level] ?? 'bg-surface-2'

const byDate = computed(() => new Map(props.days.map(d => [d.date, d])))

// Колонки — недели с понедельника; пустые ячейки до 1 января и после 31 декабря прозрачны.
const cells = computed(() => {
  const first = new Date(props.year, 0, 1)
  const last = new Date(props.year, 11, 31)
  const lead = (first.getDay() + 6) % 7 // 0 = понедельник
  const out: Array<{ key: string; cls: string; day: HeatmapDay | null }> = []
  for (let i = 0; i < lead; i++) {
    out.push({ key: `lead-${i}`, cls: 'opacity-0 pointer-events-none', day: null })
  }
  const cursor = new Date(first)
  while (cursor <= last) {
    const iso = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, '0')}-${String(cursor.getDate()).padStart(2, '0')}`
    const day = byDate.value.get(iso) ?? null
    out.push({
      key: iso,
      cls: levelClass(day?.level ?? 0) + (day ? '' : ' pointer-events-none'),
      day
    })
    cursor.setDate(cursor.getDate() + 1)
  }
  return out
})

const monthLabels = computed(() => {
  const names = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
  const first = new Date(props.year, 0, 1)
  const lead = (first.getDay() + 6) % 7
  const out: Array<{ label: string; weeks: number; offset: number }> = []
  for (let m = 0; m < 12; m++) {
    const start = Math.floor((lead + dayOfYear(new Date(props.year, m, 1))) / 7)
    const end = Math.floor((lead + dayOfYear(new Date(props.year, m + 1, 0))) / 7)
    out.push({ label: names[m]!, weeks: Math.max(end - start + (m === 11 ? 1 : 0), 1), offset: m })
  }
  return out
})

const dayOfYear = (d: Date) =>
  Math.floor((d.getTime() - new Date(d.getFullYear(), 0, 1).getTime()) / 86400000)

onMounted(() => {
  // Прокрутить к текущему месяцу (правому краю для текущего года)
  nextTick(() => {
    const el = scroller.value
    if (!el) return
    if (props.year === new Date().getFullYear()) {
      const progress = dayOfYear(new Date()) / 365
      el.scrollLeft = Math.max(el.scrollWidth * progress - el.clientWidth * 0.6, 0)
    }
  })
})
</script>
