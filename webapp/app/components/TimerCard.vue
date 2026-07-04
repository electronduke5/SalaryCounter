<template>
  <section class="card relative mb-4 overflow-hidden border-ember/25 p-5">
    <div
      class="pointer-events-none absolute -top-20 right-0 h-40 w-56 rounded-full opacity-15 blur-3xl"
      style="background: radial-gradient(ellipse, #ffb454 0%, transparent 70%)"
    />
    <div class="relative flex items-center gap-2">
      <span class="pulse-dot size-2 rounded-full bg-ember" />
      <p class="text-[11px] font-bold uppercase tracking-[0.18em] text-ember">Таймер запущен</p>
    </div>
    <p v-if="taskName" class="relative mt-2 truncate text-sm font-semibold text-ink">
      {{ taskName }}
    </p>
    <div class="relative mt-1 font-display text-[32px] font-bold tabular-nums leading-none text-ember">
      {{ elapsed }}
    </div>
    <AppButton
      class="relative mt-4"
      variant="danger"
      icon="i-lucide-square"
      :loading="stopping"
      @click="$emit('stop')"
    >
      Остановить
    </AppButton>
  </section>
</template>

<script setup lang="ts">
const props = defineProps<{
  start: number
  taskName?: string
  stopping?: boolean
}>()

defineEmits<{ stop: [] }>()

const elapsed = ref('0:00:00')
let interval: ReturnType<typeof setInterval> | null = null

const tick = () => {
  elapsed.value = formatElapsed(Math.max(Date.now() - props.start, 0))
}

onMounted(() => {
  tick()
  interval = setInterval(tick, 1000)
})

onUnmounted(() => {
  if (interval) clearInterval(interval)
})
</script>
