<template>
  <div class="card px-3 pb-3 pt-4">
    <div class="flex items-stretch justify-between gap-1.5">
      <div
        v-for="bar in bars"
        :key="bar.key"
        class="flex min-w-0 flex-1 flex-col items-center gap-2"
      >
        <div class="flex w-full flex-col items-center justify-end" :class="heightClass">
          <div class="mb-1 h-3 text-[10px] font-bold tabular-nums leading-none text-mist">
            {{ formatHoursShort(bar.hours) }}
          </div>
          <div
            class="w-full max-w-[2.25rem] rounded-t-md bg-acid/70 transition-all duration-500"
            :style="{ height: bar.hours ? `${Math.max(bar.share * 0.86, 6)}%` : '2px' }"
          />
        </div>
        <div class="w-full truncate text-center text-[10px] font-semibold capitalize leading-tight text-mist">
          {{ bar.label }}
        </div>
        <div
          v-if="showEarnings"
          class="w-full truncate text-center text-[10px] font-bold tabular-nums leading-none text-acid"
        >
          {{ bar.earnings ? formatMoneyShort(bar.earnings) : '' }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
interface BarItem {
  key: string | number
  label: string
  hours: number
  earnings?: number
}

const props = withDefaults(
  defineProps<{
    items: BarItem[]
    showEarnings?: boolean
    heightClass?: string
  }>(),
  { showEarnings: true, heightClass: 'h-36' }
)

const bars = computed(() => {
  const max = Math.max(...props.items.map(i => i.hours ?? 0), 0.01)
  return props.items.map(i => ({
    key: i.key,
    label: i.label,
    hours: i.hours ?? 0,
    earnings: i.earnings ?? 0,
    share: ((i.hours ?? 0) / max) * 100
  }))
})
</script>
