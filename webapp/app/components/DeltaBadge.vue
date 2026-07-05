<template>
  <span class="inline-flex items-center gap-0.5 font-bold tabular-nums" :class="tone">
    <UIcon :name="icon" class="size-3.5" />
    {{ text }}
  </span>
</template>

<script setup lang="ts">
const props = defineProps<{
  // Percent change vs previous period; null when previous is 0 (can't divide).
  pct: number | null
  // Whether the current period has any value (used when pct is null).
  hasCurrent?: boolean
}>()

const state = computed<'up' | 'down' | 'flat'>(() => {
  if (props.pct === null) return props.hasCurrent ? 'up' : 'flat'
  if (props.pct > 0.5) return 'up'
  if (props.pct < -0.5) return 'down'
  return 'flat'
})

const tone = computed(
  () =>
    ({ up: 'text-emerald-400', down: 'text-red-400', flat: 'text-mist' })[state.value]
)

const icon = computed(
  () =>
    ({
      up: 'i-lucide-trending-up',
      down: 'i-lucide-trending-down',
      flat: 'i-lucide-minus'
    })[state.value]
)

const text = computed(() => {
  if (props.pct === null) return props.hasCurrent ? 'новое' : '—'
  return `${Math.abs(Math.round(props.pct))}%`
})
</script>
