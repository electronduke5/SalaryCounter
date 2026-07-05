<template>
  <div class="page">
    <AppHeader kicker="Аналитика" :title="viewTitle" />

    <div class="reveal mb-3">
      <SegmentedControl v-model="activeView" :options="views" />
    </div>

    <!-- Активность: heatmap + норма часов -->
    <template v-if="activeView === 'activity'">
      <template v-if="activityLoading">
        <SkeletonBlock height="12rem" radius="1.375rem" class="mb-4" />
        <SkeletonBlock height="8rem" radius="1.375rem" />
      </template>
      <template v-else>
        <HeatmapCalendar
          class="reveal mb-4"
          :year="heatmapYear"
          :days="heatmapDays"
        />

        <section class="card reveal mb-4 p-5" style="animation-delay: 60ms">
          <h2 class="mb-4 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">
            <UIcon name="i-lucide-gauge" class="size-4" />
            Норма часов в месяц
          </h2>

          <template v-if="norm.norm > 0">
            <div class="mb-2 flex items-baseline justify-between">
              <span class="font-display text-lg font-bold tabular-nums text-ink">
                {{ formatHoursLabel(norm.actual_hours) }}
              </span>
              <span class="text-sm font-semibold text-mist">из {{ formatHoursLabel(norm.norm) }}</span>
            </div>
            <div class="relative mb-3 h-2.5 overflow-hidden rounded-full bg-surface-2">
              <div
                class="h-full rounded-full bg-acid transition-[width] duration-700"
                :style="{ width: `${Math.min((norm.actual_hours / norm.norm) * 100, 100)}%` }"
              />
              <div
                v-if="norm.expected_by_today !== null"
                class="absolute top-0 h-full w-0.5 bg-ink/60"
                :style="{ left: `${Math.min((norm.expected_by_today / norm.norm) * 100, 100)}%` }"
              />
            </div>
            <p class="text-xs font-semibold" :class="(norm.diff ?? 0) >= 0 ? 'text-acid' : 'text-ember'">
              {{ normDiffLabel }}
            </p>
          </template>

          <p v-else class="mb-3 text-[13px] leading-relaxed text-mist">
            Задайте норму часов на месяц, чтобы видеть темп и переработки.
          </p>

          <div class="mt-3 flex gap-2">
            <input
              v-model="normStr"
              type="number"
              min="0"
              inputmode="numeric"
              placeholder="Например, 160"
              class="field flex-1"
              :disabled="normSaving"
            />
            <AppButton :loading="normSaving" :disabled="normStr === ''" @click="saveNorm">
              Сохранить
            </AppButton>
          </div>
        </section>
      </template>
    </template>

    <!-- Задачи / Проекты: общие фильтры периода -->
    <div v-if="activeView !== 'activity'" class="reveal mb-4 space-y-2">
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

    <template v-if="activeView !== 'activity' && loading">
      <div class="mb-4 flex gap-2">
        <SkeletonBlock v-for="i in 3" :key="i" height="5rem" radius="1.375rem" class="flex-1" />
      </div>
      <div class="space-y-2">
        <SkeletonBlock v-for="i in 4" :key="i" height="4.5rem" radius="1.375rem" />
      </div>
    </template>

    <div
      v-else-if="activeView !== 'activity' && error"
      class="card reveal border-red-500/25 bg-red-500/8 p-4"
    >
      <p class="text-sm font-semibold text-red-300">{{ error }}</p>
    </div>

    <!-- Проекты -->
    <template v-else-if="activeView === 'projects'">
      <DonutChart v-if="projects.length" class="reveal mb-4" :items="projects" />

      <section v-if="projects.length" class="reveal" style="animation-delay: 60ms">
        <h2 class="mb-2.5 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">Проекты</h2>
        <div class="space-y-2">
          <div v-for="p in projectRows" :key="p.name" class="card px-4 py-3.5">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1 truncate text-[14px] font-semibold leading-tight text-ink">
                {{ p.name }}
              </div>
              <div class="shrink-0 text-right">
                <div class="text-sm font-bold tabular-nums text-ink">
                  {{ formatHoursLabel(p.hours) }}
                </div>
                <div class="text-xs font-bold tabular-nums text-acid">
                  {{ formatMoney(p.earnings) }} ₽
                </div>
              </div>
            </div>
            <div class="mt-2.5 h-1 overflow-hidden rounded-full bg-surface-2">
              <div
                class="h-full rounded-full bg-acid/70 transition-all duration-500"
                :style="{ width: `${p.barShare}%` }"
              />
            </div>
          </div>
        </div>
      </section>

      <EmptyState
        v-else
        class="reveal"
        icon="i-lucide-folder-open"
        title="Нет данных за выбранный период"
        hint="Синхронизируйте ClickUp, чтобы увидеть разбивку по проектам"
      />
    </template>

    <template v-else-if="activeView === 'tasks'">
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

const views = [
  { value: 'tasks', label: 'Задачи' },
  { value: 'projects', label: 'Проекты' },
  { value: 'activity', label: 'Активность' }
]
const activeView = ref('tasks')
const viewTitle = computed(
  () => ({ tasks: 'По задачам', projects: 'По проектам', activity: 'Активность' })[activeView.value] ?? 'Аналитика'
)

// Проекты
const projects = ref<any[]>([])
const projectRows = computed(() => {
  const max = Math.max(...projects.value.map(p => p.hours ?? 0), 0.01)
  return projects.value.map(p => ({
    name: p.project_name,
    hours: p.hours ?? 0,
    earnings: p.earnings ?? 0,
    barShare: ((p.hours ?? 0) / max) * 100
  }))
})

// Активность: heatmap + норма
const activityLoading = ref(true)
const activityLoaded = ref(false)
const heatmapYear = new Date().getFullYear()
const heatmapDays = ref<any[]>([])
const norm = ref<{ norm: number; actual_hours: number; expected_by_today: number | null; diff: number | null }>({
  norm: 0,
  actual_hours: 0,
  expected_by_today: null,
  diff: null
})
const normStr = ref('')
const normSaving = ref(false)
const { haptic } = useTelegram()

const normDiffLabel = computed(() => {
  const diff = norm.value.diff ?? 0
  const label = formatHoursLabel(Math.abs(diff))
  return diff >= 0 ? `Опережение темпа на ${label}` : `Отставание от темпа на ${label}`
})

const loadActivity = async () => {
  activityLoading.value = true
  try {
    const [heatmapRes, normRes] = await Promise.all([
      api.get(`/analytics/heatmap?year=${heatmapYear}`).catch(() => null),
      api.get('/analytics/norm').catch(() => null)
    ])
    heatmapDays.value = heatmapRes?.days ?? []
    if (normRes) norm.value = normRes
    activityLoaded.value = true
  } finally {
    activityLoading.value = false
  }
}

const saveNorm = async () => {
  const hours = parseFloat(normStr.value)
  if (Number.isNaN(hours) || hours < 0) return
  normSaving.value = true
  try {
    await api.put('/user/hours-norm', { hours })
    normStr.value = ''
    const normRes = await api.get('/analytics/norm')
    norm.value = normRes
    haptic.success()
  } catch {
    haptic.error()
  } finally {
    normSaving.value = false
  }
}

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
    if (activeView.value === 'projects') {
      const res = await api.get(`/analytics/projects?${query}`)
      projects.value = Array.isArray(res.projects) ? res.projects : []
    } else {
      const res = await api.get(`/analytics/tasks?${query}`)
      taskList.value = Array.isArray(res.tasks) ? res.tasks : []
      breakdown.value = res.breakdown ?? null
      summary.value = {
        total_hours: res.total_hours ?? 0,
        total_earnings: res.total_earnings ?? 0
      }
    }
  } catch (e: any) {
    error.value = e.message
    taskList.value = []
    projects.value = []
    breakdown.value = null
    summary.value = { total_hours: 0, total_earnings: 0 }
  } finally {
    loading.value = false
  }
}

const currentQuery = () => {
  const r = customRange.value
  if (isCustom.value && r) return `start=${r.start}&end=${r.end}`
  return `period=${activePeriod.value || 'week'}`
}

// Переключение вкладки: активность грузится один раз, задачи/проекты — по текущему периоду.
watch(activeView, (view) => {
  if (view === 'activity') {
    if (!activityLoaded.value) loadActivity()
    return
  }
  load(currentQuery())
})

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
