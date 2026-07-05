<template>
  <div class="page">
    <AppHeader back kicker="ClickUp" title="Синхронизация" />

    <!-- Status -->
    <template v-if="statusLoading">
      <SkeletonBlock height="5rem" radius="1.375rem" class="mb-4" />
    </template>

    <section v-else class="card reveal mb-4 flex items-center gap-3 p-5">
      <span
        class="grid size-11 shrink-0 place-items-center rounded-xl"
        :class="status?.configured ? 'bg-acid/12 text-acid' : 'bg-red-500/12 text-red-300'"
      >
        <UIcon :name="status?.configured ? 'i-lucide-plug-zap' : 'i-lucide-unplug'" class="size-5" />
      </span>
      <div class="min-w-0 flex-1">
        <div class="text-[15px] font-bold text-ink">
          {{ status?.configured ? 'ClickUp подключён' : 'ClickUp не подключён' }}
        </div>
        <div class="truncate text-xs text-mist">
          {{ status?.configured ? (status?.username ?? '') : 'Настройте интеграцию в разделе Настройки' }}
        </div>
      </div>
    </section>

    <p v-if="statusError" class="mb-4 text-sm font-semibold text-red-300">{{ statusError }}</p>

    <!-- Active timer -->
    <TimerCard
      v-if="status?.active_timer"
      class="reveal"
      style="animation-delay: 60ms"
      :start="status.active_timer.start"
      :task-name="status.active_timer.task_name"
      :stopping="stopping"
      @stop="stopTimer"
    />

    <!-- Sync actions -->
    <div v-if="status?.configured" class="reveal mb-4 space-y-3" style="animation-delay: 120ms">
      <AppButton
        block
        icon="i-lucide-refresh-cw"
        :loading="syncing === 1"
        :disabled="syncing !== null"
        @click="sync(1)"
      >
        Синхронизировать сегодня
      </AppButton>
      <AppButton
        block
        variant="ghost"
        icon="i-lucide-calendar-sync"
        :loading="syncing === 7"
        :disabled="syncing !== null"
        @click="sync(7)"
      >
        Синхронизировать 7 дней
      </AppButton>
    </div>

    <!-- Result -->
    <section
      v-if="syncResult"
      class="card reveal p-5"
      :class="syncResult.success ? 'border-acid/25' : 'border-red-500/25'"
    >
      <div
        class="mb-3 flex items-center gap-2 text-sm font-bold"
        :class="syncResult.success ? 'text-acid' : 'text-red-300'"
      >
        <UIcon
          :name="syncResult.success ? 'i-lucide-check-circle-2' : 'i-lucide-alert-circle'"
          class="size-5"
        />
        {{ syncResult.success ? 'Синхронизация завершена' : 'Ошибка синхронизации' }}
      </div>
      <div class="space-y-2 text-sm text-mist">
        <div v-if="syncResult.synced_count !== undefined" class="flex justify-between">
          <span>Добавлено записей</span>
          <span class="font-bold tabular-nums text-ink">{{ syncResult.synced_count }}</span>
        </div>
        <div v-if="syncResult.total_hours !== undefined" class="flex justify-between">
          <span>Всего часов</span>
          <span class="font-bold tabular-nums text-ink">{{ formatHoursLabel(syncResult.total_hours) }}</span>
        </div>
        <div v-if="syncResult.total_earnings !== undefined" class="flex justify-between">
          <span>Заработано</span>
          <span class="font-bold tabular-nums text-acid">{{ formatMoney(syncResult.total_earnings) }} ₽</span>
        </div>
        <p v-if="syncResult.message">{{ syncResult.message }}</p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
const api = useApi()
const { haptic } = useTelegram()

const statusLoading = ref(true)
const statusError = ref<string | null>(null)
const status = ref<any>(null)
const syncing = ref<number | null>(null)
const stopping = ref(false)
const syncResult = ref<any>(null)

const sync = async (days: number) => {
  syncing.value = days
  syncResult.value = null
  try {
    const res = await api.post('/clickup/sync', { days })
    syncResult.value = { ...res, success: true }
    haptic.success()
  } catch (e: any) {
    syncResult.value = { success: false, message: e.message }
    haptic.error()
  } finally {
    syncing.value = null
  }
}

const stopTimer = async () => {
  stopping.value = true
  try {
    await api.post('/clickup/timer/stop')
    if (status.value) status.value.active_timer = null
    haptic.success()
  } catch (e: any) {
    statusError.value = e.message
    haptic.error()
  } finally {
    stopping.value = false
  }
}

onMounted(async () => {
  try {
    status.value = await api.get('/clickup/status')
  } catch (e: any) {
    statusError.value = e.message
  } finally {
    statusLoading.value = false
  }
})
</script>
