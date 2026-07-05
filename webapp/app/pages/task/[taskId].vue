<template>
  <div class="page">
    <AppHeader back kicker="ClickUp" title="Задача" />

    <template v-if="loading">
      <SkeletonBlock height="10rem" radius="1.375rem" class="mb-4" />
      <SkeletonBlock height="3.5rem" radius="1rem" class="mb-4" />
      <SkeletonBlock height="8rem" radius="1.375rem" />
    </template>

    <div v-else-if="error" class="card reveal border-red-500/25 bg-red-500/8 p-4">
      <p class="text-sm font-semibold text-red-300">{{ error }}</p>
    </div>

    <template v-else-if="task">
      <!-- Task info -->
      <section class="card reveal mb-4 p-5">
        <div class="mb-3 flex items-start justify-between gap-3">
          <h2 class="min-w-0 font-display text-[17px] font-semibold leading-snug text-ink">
            {{ task.name }}
          </h2>
          <StatusBadge class="shrink-0" :status="task.status?.status ?? task.status" />
        </div>

        <p v-if="task.description" class="mb-4 text-[13px] leading-relaxed text-mist">
          {{ task.description }}
        </p>

        <div class="space-y-2.5">
          <div v-if="task.assignees?.length" class="flex items-center gap-2.5 text-sm">
            <UIcon name="i-lucide-user" class="size-4 shrink-0 text-mist" />
            <span class="text-mist">Исполнитель</span>
            <span class="ml-auto font-semibold text-ink">
              {{ task.assignees[0].username ?? task.assignees[0].email }}
            </span>
          </div>
          <div v-if="task.due_date" class="flex items-center gap-2.5 text-sm">
            <UIcon name="i-lucide-calendar" class="size-4 shrink-0 text-mist" />
            <span class="text-mist">Срок</span>
            <span class="ml-auto font-semibold text-ink">{{ formatDue(task.due_date) }}</span>
          </div>
          <div v-if="task.list?.name" class="flex items-center gap-2.5 text-sm">
            <UIcon name="i-lucide-list" class="size-4 shrink-0 text-mist" />
            <span class="text-mist">Список</span>
            <span class="ml-auto truncate font-semibold text-ink">{{ task.list.name }}</span>
          </div>
          <div v-if="task.folder?.name" class="flex items-center gap-2.5 text-sm">
            <UIcon name="i-lucide-folder" class="size-4 shrink-0 text-mist" />
            <span class="text-mist">Папка</span>
            <span class="ml-auto truncate font-semibold text-ink">{{ task.folder.name }}</span>
          </div>
        </div>
      </section>

      <!-- Timer -->
      <TimerCard
        v-if="isTimerActive"
        class="reveal"
        :start="timerStart"
        :stopping="timerLoading"
        @stop="stopTimer"
      />
      <section v-else class="reveal mb-4" style="animation-delay: 60ms">
        <AppButton block icon="i-lucide-play" :loading="timerLoading" @click="startTimer">
          Запустить таймер
        </AppButton>
      </section>

      <!-- Status change -->
      <section class="card reveal p-5" style="animation-delay: 120ms">
        <h2 class="mb-3 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">
          Изменить статус
        </h2>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="s in statuses"
            :key="s"
            class="inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-[13px] font-bold transition-all active:scale-95 disabled:opacity-50"
            :class="
              currentStatus === s.toLowerCase()
                ? 'bg-acid text-[#0d1206]'
                : 'bg-surface-2 text-mist border border-edge'
            "
            :disabled="statusLoading !== null"
            @click="changeStatus(s)"
          >
            <UIcon
              v-if="statusLoading === s"
              name="i-lucide-loader-circle"
              class="size-3.5 animate-spin"
            />
            {{ s }}
          </button>
        </div>
        <p v-if="statusError" class="mt-3 text-sm font-semibold text-red-300">{{ statusError }}</p>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
const api = useApi()
const route = useRoute()
const { haptic } = useTelegram()

const taskId = computed(() => route.params.taskId as string)
const loading = ref(true)
const error = ref<string | null>(null)
const task = ref<any>(null)
const timerLoading = ref(false)
const statusLoading = ref<string | null>(null)
const statusError = ref<string | null>(null)
const isTimerActive = ref(false)
const timerStart = ref(Date.now())

const statuses = ['Open', 'In Progress', 'Review', 'Done', 'Complete']

const currentStatus = computed(() =>
  (task.value?.status?.status ?? task.value?.status ?? '').toLowerCase()
)

const formatDue = (ts: string | number) => {
  const d = new Date(typeof ts === 'string' ? ts : Number(ts))
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

const startTimer = async () => {
  timerLoading.value = true
  try {
    const res = await api.post(`/clickup/tasks/${taskId.value}/timer/start`)
    timerStart.value = res.start ?? Date.now()
    isTimerActive.value = true
    haptic.success()
  } catch (e: any) {
    error.value = e.message
    haptic.error()
  } finally {
    timerLoading.value = false
  }
}

const stopTimer = async () => {
  timerLoading.value = true
  try {
    await api.post('/clickup/timer/stop')
    isTimerActive.value = false
    haptic.success()
  } catch (e: any) {
    error.value = e.message
    haptic.error()
  } finally {
    timerLoading.value = false
  }
}

const changeStatus = async (status: string) => {
  statusLoading.value = status
  statusError.value = null
  try {
    await api.put(`/clickup/tasks/${taskId.value}/status`, { status })
    if (task.value) {
      if (typeof task.value.status === 'object') {
        task.value.status.status = status
      } else {
        task.value.status = status
      }
    }
    haptic.success()
  } catch (e: any) {
    statusError.value = e.message
    haptic.error()
  } finally {
    statusLoading.value = null
  }
}

onMounted(async () => {
  try {
    const [taskData, statusData] = await Promise.all([
      api.get(`/clickup/tasks/${taskId.value}`),
      api.get('/clickup/status').catch(() => null)
    ])
    task.value = taskData
    if (statusData?.active_timer?.task_id === taskId.value) {
      isTimerActive.value = true
      timerStart.value = statusData.active_timer.start ?? Date.now()
    }
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})
</script>
