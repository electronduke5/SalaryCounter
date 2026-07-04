<template>
  <section class="card relative mb-4 overflow-hidden p-6">
    <!-- Accent glow behind the number -->
    <div
      class="pointer-events-none absolute -top-24 left-1/2 h-56 w-80 -translate-x-1/2 rounded-full opacity-25 blur-3xl"
      style="background: radial-gradient(ellipse, #c6f455 0%, transparent 70%)"
    />
    <p class="relative text-[11px] font-bold uppercase tracking-[0.18em] text-mist">{{ label }}</p>
    <div class="relative mt-2 font-display text-[42px] font-bold leading-none tabular-nums text-ink">
      {{ formatMoney(display) }}<span class="ml-1.5 text-[26px] text-acid">₽</span>
    </div>
    <div class="relative mt-3 flex items-center gap-1.5 text-sm font-semibold text-mist">
      <UIcon name="i-lucide-clock" class="size-4" />
      {{ formatHoursLabel(hours) }}
    </div>
    <div v-if="$slots.default" class="relative mt-5">
      <slot />
    </div>
  </section>
</template>

<script setup lang="ts">
const props = withDefaults(
  defineProps<{ amount: number; hours: number; label?: string }>(),
  { label: 'Заработано сегодня' }
)

const display = ref(0)
let raf = 0

const animateTo = (target: number) => {
  cancelAnimationFrame(raf)
  const from = display.value
  const start = performance.now()
  const duration = 700
  const tick = (now: number) => {
    const t = Math.min((now - start) / duration, 1)
    const eased = 1 - Math.pow(1 - t, 3)
    display.value = from + (target - from) * eased
    if (t < 1) raf = requestAnimationFrame(tick)
  }
  raf = requestAnimationFrame(tick)
}

watch(() => props.amount, animateTo, { immediate: true })
onUnmounted(() => cancelAnimationFrame(raf))
</script>
