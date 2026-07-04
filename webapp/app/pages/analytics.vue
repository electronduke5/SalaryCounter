<template>
  <div class="page">
    <AppHeader kicker="Аналитика" title="По задачам" />

    <div class="reveal mb-4 space-y-2">
      <SegmentedControl v-model="activePeriod" :options="periods" />
      <UPopover
        v-model:open="calendarOpen"
        :ui="{ content: 'bg-surface border border-edge text-ink rounded-2xl' }"
      >
        <button
          type="button"
          class="flex w-full items-center justify-center gap-2 rounded-full px-3.5 py-2 text-[13px] font-bold transition-all active:scale-95"
          :class="isCustom ? 'bg-acid text-[#0d1206]' : 'border border-edge bg-surface-2 text-mist'"
        >
          <UIcon name="i-lucide-calendar" class="size-4" />
          {{ customLabel }}
        </button>
        <template #content>
          <div class="p-2">
            <UCalendar v-model="range" range :max-value="maxDate" :ui="{ headCell: 'text-mist' }" />
            <div class="mt-2 flex gap-2">
              <button
                type="button"
                class="flex-1 rounded-lg bg-acid px-3 py-2 text-[13px] font-bold text-[#0d1206] disabled:opacity-40"
                :disabled="!range?.start || !range?.end"
                @click="applyRange"
              >
                Применить
              </button>
              <button
                type="button"
                class="rounded-lg border border-edge bg-surface-2 px-3 py-2 text-[13px] font-bold text-mist"
                @click="resetRange"
              >
                Сбросить
              </button>
            </div>
          </div>
        </template>
      </UPopover>
    </div>

    <template v-if="loading">
      <div class="mb-4 flex gap-2">
        <SkeletonBlock v-for="i in 3" :key="i" height="5rem" radius="1.375rem" class="flex-1" />
      </div>
      <div class="space-y-2">
        <SkeletonBlock v-for="i in 4" :key="i" height="4.5rem" radius="1.375rem" />
      </div>
    </template>

    <div v-else-if="error" class="card reveal border-red-500/25 bg-red-500/8 p-4">
      <p class="text-sm font-semibold text-red-300">{{ error }}</p>
    </div>

    <template v-else>
      <!-- Summary stat tiles -->
      <div class="reveal mb-4 grid grid-cols-3 gap-2">
        <div class="card px-3 py-4 text-center">
          <div class="font-display text-lg font-bold tabular-nums text-ink">
            {{ formatHoursLabel(summary.total_hours) }}
          </div>
          <div class="mt-1 text-[10px] font-bold uppercase tracking-wider text-mist">Часов</div>
        </div>
        <div class="card px-3 py-4 text-center">
          <div class="font-display text-lg font-bold tabular-nums text-acid">
            {{ formatMoney(summary.total_earnings) }}
          </div>
          <div class="mt-1 text-[10px] font-bold uppercase tracking-wider text-mist">Рублей</div>
        </div>
        <div class="card px-3 py-4 text-center">
          <div class="font-display text-lg font-bold tabular-nums text-ink">{{ taskList.length }}</div>
          <div class="mt-1 text-[10px] font-bold uppercase tracking-wider text-mist">Задач</div>
        </div>
      </div>

      <!-- Period breakdown: vertical bar chart by days/weeks/months -->
      <section v-if="breakdownRows.length > 1" class="reveal mb-4" style="animation-delay: 60ms">
        <div class="mb-2.5 flex items-center justify-between gap-3">
          <h2 class="text-[11px] font-bold uppercase tracking-[0.18em] text-mist">
            {{ breakdownTitle }}
          </h2>
          <div class="flex items-center gap-3 text-[10px] font-bold">
            <span class="flex items-center gap-1 text-mist">
              <span class="size-1.5 rounded-full bg-mist" />
              часы
            </span>
            <span class="flex items-center gap-1 text-acid">
              <span class="size-1.5 rounded-full bg-acid" />
              рубли
            </span>
          </div>
        </div>
        <BarChart :items="breakdownRows" />
      </section>

      <!-- Task breakdown with time-share bars -->
      <section v-if="taskList.length" class="reveal" style="animation-delay: 80ms">
        <h2 class="mb-2.5 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">Задачи</h2>
        <div class="space-y-2">
          <div v-for="task in taskRows" :key="task.key" class="card px-4 py-3.5">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="truncate text-[14px] font-semibold leading-tight text-ink">
                  {{ task.name }}
                </div>
                <div v-if="task.listName" class="mt-0.5 truncate text-xs text-mist">
                  {{ task.listName }}
                </div>
              </div>
              <div class="shrink-0 text-right">
                <div class="text-sm font-bold tabular-nums text-ink">
                  {{ formatHoursLabel(task.hours) }}
                </div>
                <div class="text-xs font-bold tabular-nums text-acid">
                  {{ formatMoney(task.earnings) }} ₽
                </div>
              </div>
            </div>
            <div class="mt-2.5 h-1 overflow-hidden rounded-full bg-surface-2">
              <div
                class="h-full rounded-full bg-acid/70 transition-all duration-500"
                :style="{ width: `${task.share}%` }"
              />
            </div>
          </div>
        </div>
      </section>

      <EmptyState
        v-else
        class="reveal"
        style="animation-delay: 80ms"
        icon="i-lucide-chart-pie"
        title="Нет данных за выбранный период"
        hint="Синхронизируйте ClickUp или добавьте время вручную"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { today, getLocalTimeZone } from '@internationalized/date'

const api = useApi()

// Cap the range calendar at today — future dates can't be selected.
const maxDate = today(getLocalTimeZone())

const periods = [
  { value: 'today', label: 'Сегодня' },
  { value: 'yesterday', label: 'Вчера' },
  { value: 'week', label: 'Неделя' },
  { value: 'last_week', label: 'Прош. неделя' },
  { value: 'month', label: 'Месяц' },
  { value: 'last_month', label: 'Прош. месяц' },
  { value: 'year', label: 'Год' },
  { value: 'last_year', label: 'Прош. год' }
]

const activePeriod = ref('week')
// reka-ui's RangeCalendar dereferences modelValue.value.start unless the value is
// strictly `undefined`; passing `null` throws during setup, so keep it undefined.
const range = ref<{ start?: any; end?: any } | undefined>()
const customRange = ref<{ start: string; end: string } | null>(null)
const calendarOpen = ref(false)
const loading = ref(true)
const error = ref<string | null>(null)
const summary = ref({ total_hours: 0, total_earnings: 0 })
const taskList = ref<any[]>([])
const breakdown = ref<{ type: string; items: any[] } | null>(null)

const isCustom = computed(() => activePeriod.value === '')
const customLabel = computed(() => {
  const r = customRange.value
  if (isCustom.value && r) {
    const short = (d: string) => d.split('-').slice(1).reverse().join('.')
    return `${short(r.start)} — ${short(r.end)}`
  }
  return 'Свой период'
})

const breakdownTitle = computed(() => {
  const t = breakdown.value?.type
  return t === 'months' ? 'По месяцам' : t === 'weeks' ? 'По неделям' : 'По дням'
})

const breakdownRows = computed(() => {
  const items = breakdown.value?.items ?? []
  const max = Math.max(...items.map(i => i.hours ?? 0), 0.01)
  return items.map((i, idx) => ({
    key: i.date ?? i.number ?? idx,
    label: i.label ?? '',
    sub: i.sub ?? '',
    hours: i.hours ?? 0,
    earnings: i.earnings ?? 0,
    share: ((i.hours ?? 0) / max) * 100
  }))
})

const taskRows = computed(() => {
  const max = Math.max(...taskList.value.map(t => t.hours ?? 0), 0.01)
  return taskList.value.map((t, i) => ({
    key: t.task_id ?? t.name ?? i,
    name: t.task_name ?? t.name ?? 'Без названия',
    listName: t.list_name ?? '',
    hours: t.hours ?? 0,
    earnings: t.earnings ?? 0,
    share: ((t.hours ?? 0) / max) * 100
  }))
})

const load = async (query: string) => {
  loading.value = true
  error.value = null
  try {
    const res = await api.get(`/analytics/tasks?${query}`)
    taskList.value = Array.isArray(res.tasks) ? res.tasks : []
    breakdown.value = res.breakdown ?? null
    summary.value = {
      total_hours: res.total_hours ?? 0,
      total_earnings: res.total_earnings ?? 0
    }
  } catch (e: any) {
    error.value = e.message
    taskList.value = []
    breakdown.value = null
    summary.value = { total_hours: 0, total_earnings: 0 }
  } finally {
    loading.value = false
  }
}

const applyRange = () => {
  if (!range.value?.start || !range.value?.end) return
  const start = range.value.start.toString()
  const end = range.value.end.toString()
  customRange.value = { start, end }
  calendarOpen.value = false
  activePeriod.value = '' // deselect preset chips; watcher below ignores empty
  load(`start=${start}&end=${end}`)
}

const resetRange = () => {
  range.value = undefined
  customRange.value = null
  calendarOpen.value = false
  activePeriod.value = 'week' // triggers the watcher → reloads the week preset
}

// Selecting a preset chip clears any custom range and loads that preset.
watch(activePeriod, (period) => {
  if (!period) return
  range.value = undefined
  customRange.value = null
  load(`period=${period}`)
})

onMounted(() => load(`period=${activePeriod.value}`))
</script>
