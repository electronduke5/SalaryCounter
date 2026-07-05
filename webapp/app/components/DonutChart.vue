<template>
  <section class="card p-5">
    <div class="flex items-center gap-5">
      <div class="relative size-32 shrink-0">
        <svg viewBox="0 0 42 42" class="size-full -rotate-90">
          <circle cx="21" cy="21" r="15.9155" fill="none" class="stroke-surface-2" stroke-width="5" />
          <circle
            v-for="seg in segments"
            :key="seg.key"
            cx="21"
            cy="21"
            r="15.9155"
            fill="none"
            :stroke="seg.color"
            stroke-width="5"
            stroke-linecap="butt"
            :stroke-dasharray="`${seg.length} ${100 - seg.length}`"
            :stroke-dashoffset="-seg.offset"
            class="transition-all duration-700"
          />
        </svg>
        <div class="absolute inset-0 grid place-items-center text-center">
          <div>
            <div class="font-display text-sm font-bold tabular-nums text-ink">
              {{ formatMoneyShort(totalEarnings) }}₽
            </div>
            <div class="text-[9px] font-bold uppercase tracking-wider text-mist">
              {{ formatHoursLabel(totalHours) }}
            </div>
          </div>
        </div>
      </div>

      <div class="min-w-0 flex-1 space-y-2">
        <div v-for="seg in segments" :key="seg.key" class="flex items-center gap-2">
          <span class="size-2.5 shrink-0 rounded-full" :style="{ background: seg.color }" />
          <span class="min-w-0 flex-1 truncate text-xs font-semibold text-ink">{{ seg.name }}</span>
          <span class="shrink-0 text-xs font-bold tabular-nums text-mist">{{ seg.percent }}%</span>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
export interface DonutItem {
  project_name: string
  hours: number
  earnings: number
  share: number
}

const props = defineProps<{ items: DonutItem[] }>()

const PALETTE = ['#c6f455', '#ffb454', '#7dd3fc', '#f0abfc', '#a3e635', '#fda4af', '#94a3b8']
const MAX_SEGMENTS = 6

const totalEarnings = computed(() => props.items.reduce((s, i) => s + i.earnings, 0))
const totalHours = computed(() => props.items.reduce((s, i) => s + i.hours, 0))

// Топ-6 проектов, остальное схлопывается в «Другие»
const segments = computed(() => {
  const top = props.items.slice(0, MAX_SEGMENTS)
  const rest = props.items.slice(MAX_SEGMENTS)
  const rows = [...top]
  if (rest.length) {
    rows.push({
      project_name: 'Другие',
      hours: rest.reduce((s, i) => s + i.hours, 0),
      earnings: rest.reduce((s, i) => s + i.earnings, 0),
      share: rest.reduce((s, i) => s + i.share, 0)
    })
  }
  let offset = 0
  return rows.map((r, i) => {
    const length = Math.max(r.share * 100, 0)
    const seg = {
      key: r.project_name,
      name: r.project_name,
      color: PALETTE[i % PALETTE.length]!,
      length,
      offset,
      percent: Math.round(r.share * 100)
    }
    offset += length
    return seg
  })
})
</script>
