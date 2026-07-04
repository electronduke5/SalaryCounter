<template>
  <span
    class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold capitalize"
    :class="style.badge"
  >
    <span class="size-1.5 rounded-full" :class="style.dot" />
    {{ status || 'unknown' }}
  </span>
</template>

<script setup lang="ts">
const props = defineProps<{ status?: string }>()

const STATUS_STYLES: Record<string, { badge: string; dot: string }> = {
  'open': { badge: 'bg-sky-500/12 text-sky-300', dot: 'bg-sky-400' },
  'in progress': { badge: 'bg-amber-500/12 text-amber-300', dot: 'bg-amber-400' },
  'review': { badge: 'bg-violet-500/12 text-violet-300', dot: 'bg-violet-400' },
  'done': { badge: 'bg-lime-500/12 text-lime-300', dot: 'bg-lime-400' },
  'complete': { badge: 'bg-emerald-500/12 text-emerald-300', dot: 'bg-emerald-400' }
}

const style = computed(
  () =>
    STATUS_STYLES[(props.status ?? '').toLowerCase()] ?? {
      badge: 'bg-surface-2 text-mist',
      dot: 'bg-mist'
    }
)
</script>
