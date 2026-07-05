<template>
  <div>
    <div class="flex h-16 items-stretch gap-1.5">
      <button
        v-for="day in bars"
        :key="day.date"
        type="button"
        class="group relative flex flex-1 flex-col justify-end focus:outline-none"
        :title="`${day.weekday}: ${formatHoursLabel(day.hours)}`"
        @click="emit('select', day.date)"
      >
        <div
          v-if="day.isSelected && day.hours > 0"
          class="absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap text-[10px] font-bold text-acid"
        >
          {{ formatHoursLabel(day.hours) }}
        </div>
        <div
          class="w-full rounded-t transition-all duration-500 group-active:opacity-70"
          :class="day.isSelected ? 'bg-acid' : 'bg-acid/25'"
          :style="{ height: `${day.height}%`, minHeight: day.hours > 0 ? '4px' : '2px' }"
        />
      </button>
    </div>
    <div class="mt-1.5 flex gap-1.5">
      <div
        v-for="day in bars"
        :key="day.date"
        class="flex-1 text-center text-[10px] font-bold uppercase"
        :class="day.isSelected ? 'text-acid' : 'text-mist'"
      >
        <span :class="day.isToday ? 'underline decoration-dotted underline-offset-2' : ''">
          {{ day.weekday }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  days: { date: string; total_hours: number }[]
  selectedDate?: string
  todayDate?: string
}>()

const emit = defineEmits<{ select: [date: string] }>()

const WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб']

const bars = computed(() => {
  // Prefer the server's day (from the API) over the browser's UTC date so the
  // "today" marker and default selection line up with the backend.
  const todayStr = props.todayDate || new Date().toISOString().slice(0, 10)
  const max = Math.max(...props.days.map(d => d.total_hours ?? 0), 1)
  return props.days.map(d => ({
    date: d.date,
    hours: d.total_hours ?? 0,
    height: ((d.total_hours ?? 0) / max) * 100,
    weekday: WEEKDAYS[new Date(d.date).getDay()],
    isToday: d.date === todayStr,
    isSelected: d.date === (props.selectedDate ?? todayStr)
  }))
})
</script>
