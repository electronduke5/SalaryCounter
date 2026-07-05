<template>
  <section class="card relative mb-4 overflow-hidden p-5">
    <div
      class="pointer-events-none absolute -top-20 left-0 h-40 w-56 rounded-full opacity-15 blur-3xl"
      style="background: radial-gradient(ellipse, #c6f455 0%, transparent 70%)"
    />
    <div class="relative flex items-center justify-between">
      <p class="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">
        <UIcon name="i-lucide-target" class="size-4" />
        Цель месяца
      </p>
      <span class="font-display text-sm font-bold tabular-nums text-acid">{{ percentLabel }}</span>
    </div>

    <div class="relative mt-3 h-2.5 overflow-hidden rounded-full bg-surface-2">
      <div
        class="h-full rounded-full bg-acid transition-[width] duration-700 ease-out"
        :style="{ width: `${Math.min(percent ?? 0, 100)}%` }"
      />
    </div>

    <div class="relative mt-3 flex items-baseline justify-between">
      <span class="font-display text-lg font-bold tabular-nums text-ink">
        {{ formatMoney(progress.total) }} ₽
      </span>
      <span class="text-sm font-semibold text-mist">из {{ formatMoney(progress.goal) }} ₽</span>
    </div>

    <div class="relative mt-2 space-y-1 text-xs text-mist">
      <div class="flex justify-between">
        <span>По часам</span>
        <span class="tabular-nums">{{ formatMoney(progress.hours_earnings) }} ₽</span>
      </div>
      <div v-if="progress.bonus_earnings > 0" class="flex justify-between">
        <span>Премии</span>
        <span class="tabular-nums">{{ formatMoney(progress.bonus_earnings) }} ₽</span>
      </div>
      <div class="flex justify-between">
        <span>{{ remainingLabel }}</span>
        <span class="tabular-nums">{{ trailingLabel }}</span>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
export interface GoalProgressData {
  hours_earnings: number
  bonus_earnings: number
  total: number
  goal: number
  percent: number | null
  remaining: number | null
  days_left: number
}

const props = defineProps<{ progress: GoalProgressData }>()

const percent = computed(() => props.progress.percent ?? 0)
const percentLabel = computed(() => `${percent.value}%`)
const done = computed(() => (props.progress.remaining ?? 0) <= 0)

const remainingLabel = computed(() =>
  done.value ? 'Цель достигнута' : `Осталось (${props.progress.days_left} дн.)`
)
const trailingLabel = computed(() =>
  done.value ? '🎉' : `${formatMoney(props.progress.remaining ?? 0)} ₽`
)
</script>
