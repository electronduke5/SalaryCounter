<template>
  <div class="page">
    <AppHeader :kicker="todayLabel" :title="greeting" />

    <!-- Loading skeleton -->
    <template v-if="loading">
      <SkeletonBlock height="13rem" radius="1.375rem" class="mb-4" />
      <div class="mb-4 flex gap-3">
        <SkeletonBlock height="3.25rem" radius="1rem" class="flex-1" />
        <SkeletonBlock height="3.25rem" radius="1rem" class="flex-1" />
      </div>
      <SkeletonBlock height="8rem" radius="1.375rem" />
    </template>

    <template v-else>
      <!-- Hero: selected day's earnings + week strip -->
      <HeroEarnings
        class="reveal"
        :amount="selectedDay.total_earnings"
        :hours="selectedDay.total_hours"
        :label="heroLabel"
      >
        <WeekBars
          v-if="weekDays.length"
          :days="weekDays"
          :selected-date="selectedDate"
          :today-date="today.date"
          @select="selectDay"
        />
      </HeroEarnings>

      <!-- Active timer -->
      <TimerCard
        v-if="activeTimer"
        class="reveal"
        style="animation-delay: 60ms"
        :start="activeTimer.start"
        :task-name="activeTimer.task_name"
        :stopping="stopping"
        @stop="stopTimer"
      />

      <!-- Error -->
      <div v-if="error" class="card reveal mb-4 border-red-500/25 bg-red-500/8 p-4">
        <p class="text-sm font-semibold text-red-300">{{ error }}</p>
      </div>

      <!-- Quick actions -->
      <div class="reveal mb-6 flex gap-3" style="animation-delay: 120ms">
        <AppButton
          class="flex-1"
          icon="i-lucide-zap"
          :loading="quickSyncing"
          :disabled="quickSyncing"
          @click="quickSyncToday"
        >
          Сегодня
        </AppButton>
        <AppButton variant="ghost" icon="i-lucide-refresh-cw" @click="router.push('/sync')">
          Синхронизировать
        </AppButton>
      </div>

      <!-- Selected day's sessions -->
      <section v-if="selectedDay.sessions?.length" class="reveal" style="animation-delay: 180ms">
        <h2 class="mb-2.5 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">
          {{ sessionsTitle }}
        </h2>
        <div class="space-y-2">
          <ListRow
            v-for="(s, i) in selectedDay.sessions"
            :key="i"
            :icon="s.source === 'clickup' ? 'i-lucide-link' : 'i-lucide-pencil-line'"
            :title="s.source === 'clickup' ? (s.task_name ?? 'ClickUp') : 'Ручная запись'"
            :subtitle="s.source === 'clickup' ? (s.project_name || 'ClickUp') : 'Добавлено вручную'"
            :trailing="sessionTime(s)"
            :chevron="false"
          />
        </div>
      </section>

      <EmptyState
        v-else-if="!error"
        class="reveal"
        style="animation-delay: 180ms"
        icon="i-lucide-coffee"
        :title="isTodaySelected ? 'Сегодня записей ещё нет' : 'За этот день записей нет'"
        :hint="isTodaySelected ? 'Запустите таймер в задаче или добавьте время вручную' : 'Выберите другой день или синхронизируйте ClickUp'"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
const api = useApi()
const router = useRouter()
const { user, haptic } = useTelegram()

const loading = ref(true)
const stopping = ref(false)
const quickSyncing = ref(false)
const error = ref<string | null>(null)
const today = ref({ date: '', total_hours: 0, total_earnings: 0, sessions: [] as any[] })
const weekDays = ref<any[]>([])
const activeTimer = ref<any>(null)
const selectedDate = ref('')

const greeting = computed(() =>
  user?.first_name ? `Привет, ${user.first_name}` : 'Ваш заработок'
)

const todayLabel = new Date().toLocaleDateString('ru-RU', {
  weekday: 'long',
  day: 'numeric',
  month: 'long'
})

const isTodaySelected = computed(
  () => !selectedDate.value || selectedDate.value === today.value.date
)

// The full day record for the current selection (fresh /today data when today).
const selectedDay = computed(() => {
  if (isTodaySelected.value) return today.value
  return (
    weekDays.value.find(d => d.date === selectedDate.value) ?? {
      total_hours: 0,
      total_earnings: 0,
      sessions: []
    }
  )
})

const dayName = computed(() =>
  selectedDate.value
    ? new Date(selectedDate.value).toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'long'
      })
    : ''
)

const heroLabel = computed(() =>
  isTodaySelected.value ? 'Заработано сегодня' : `Заработано ${dayName.value}`
)

const sessionsTitle = computed(() =>
  isTodaySelected.value ? 'Сессии сегодня' : `Сессии за ${dayName.value}`
)

const selectDay = (date: string) => {
  selectedDate.value = date
  haptic.select()
}

const sessionTime = (s: any) => {
  if (s.hours !== undefined) {
    return s.minutes > 0 ? `${s.hours}ч ${s.minutes}м` : `${s.hours}ч`
  }
  return formatHoursLabel(s.total_hours ?? 0)
}

const stopTimer = async () => {
  stopping.value = true
  try {
    await api.post('/clickup/timer/stop')
    activeTimer.value = null
    haptic.success()
  } catch (e: any) {
    error.value = e.message
    haptic.error()
  } finally {
    stopping.value = false
  }
}

const loadData = async () => {
  const [todayData, statusData, weekData] = await Promise.all([
    api.get('/earnings/today'),
    api.get('/clickup/status').catch(() => null),
    api.get('/earnings/week').catch(() => null)
  ])
  today.value = todayData
  selectedDate.value = todayData.date
  weekDays.value = weekData?.days ?? []
  activeTimer.value = statusData?.active_timer ?? null
}

const quickSyncToday = async () => {
  quickSyncing.value = true
  error.value = null
  try {
    await api.post('/clickup/sync', { days: 1 })
    await loadData()
    haptic.success()
  } catch (e: any) {
    error.value = e.message
    haptic.error()
  } finally {
    quickSyncing.value = false
  }
}

onMounted(async () => {
  try {
    await loadData()
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})
</script>
