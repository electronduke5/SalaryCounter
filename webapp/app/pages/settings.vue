<template>
  <div class="page">
    <AppHeader kicker="Настройки" title="Профиль" />

    <!-- Profile card -->
    <section class="card reveal mb-4 flex items-center gap-4 p-5">
      <div
        class="grid size-14 shrink-0 place-items-center rounded-2xl bg-acid font-display text-xl font-bold text-[#0d1206]"
      >
        {{ initial }}
      </div>
      <div class="min-w-0">
        <div class="truncate font-display text-[17px] font-semibold text-ink">{{ displayName }}</div>
        <div v-if="tgUsername && tgUsername !== displayName" class="truncate text-sm text-mist">@{{ tgUsername }}</div>
      </div>
    </section>

    <!-- Rate -->
    <section class="card reveal mb-4 p-5" style="animation-delay: 60ms">
      <h2 class="mb-4 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">
        <UIcon name="i-lucide-banknote" class="size-4" />
        Ставка
      </h2>

      <div v-if="rateLoading" class="space-y-3">
        <SkeletonBlock height="2.5rem" />
      </div>

      <template v-else>
        <div class="mb-4 flex items-baseline justify-between">
          <span class="text-sm text-mist">Текущая ставка</span>
          <span class="font-display text-xl font-bold tabular-nums text-acid">
            {{ formatMoney(currentRate) }} ₽/ч
          </span>
        </div>

        <div class="flex gap-2">
          <input
            v-model="newRateStr"
            type="number"
            min="0"
            inputmode="numeric"
            placeholder="Новая ставка"
            class="field flex-1"
            :disabled="rateSaving"
          />
          <AppButton :loading="rateSaving" :disabled="!newRateStr" @click="saveRate">
            Сохранить
          </AppButton>
        </div>

        <p v-if="rateError" class="mt-2 text-sm font-semibold text-red-300">{{ rateError }}</p>
        <p v-if="rateSuccess" class="mt-2 flex items-center gap-1.5 text-sm font-semibold text-acid">
          <UIcon name="i-lucide-check" class="size-4" /> Ставка обновлена
        </p>
      </template>
    </section>

    <!-- ClickUp -->
    <section class="card reveal p-5" style="animation-delay: 120ms">
      <h2 class="mb-4 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">
        <UIcon name="i-lucide-link" class="size-4" />
        ClickUp
      </h2>

      <div v-if="clickupLoading" class="space-y-3">
        <SkeletonBlock height="4rem" />
      </div>

      <!-- Connected -->
      <template v-else-if="clickupConfigured">
        <div class="mb-4 flex items-center gap-3 rounded-2xl border border-acid/20 bg-acid/8 p-4">
          <span class="grid size-10 shrink-0 place-items-center rounded-xl bg-acid/15 text-acid">
            <UIcon name="i-lucide-check-circle-2" class="size-5" />
          </span>
          <div class="min-w-0">
            <div class="text-sm font-bold text-acid">Подключено</div>
            <div v-if="clickupUser" class="truncate text-xs text-mist">{{ clickupUser }}</div>
            <div v-if="clickupWorkspace" class="truncate text-xs text-mist">
              Workspace {{ clickupWorkspace }}
            </div>
          </div>
        </div>
        <AppButton variant="danger" icon="i-lucide-unplug" :loading="resetLoading" @click="resetClickup">
          Отключить
        </AppButton>
        <p v-if="clickupError" class="mt-2 text-sm font-semibold text-red-300">{{ clickupError }}</p>
      </template>

      <!-- Setup form -->
      <template v-else>
        <p class="mb-4 text-[13px] leading-relaxed text-mist">
          Введите Personal API Token и Workspace ID из ClickUp, чтобы синхронизировать задачи и таймеры.
        </p>

        <div class="space-y-3">
          <div>
            <label class="mb-1.5 block text-xs font-bold text-mist">Personal API Token</label>
            <input
              v-model="apiToken"
              type="password"
              placeholder="pk_..."
              class="field"
              :disabled="setupLoading"
            />
          </div>
          <div>
            <label class="mb-1.5 block text-xs font-bold text-mist">Workspace ID</label>
            <input
              v-model="workspaceId"
              placeholder="12345678"
              class="field"
              :disabled="setupLoading"
            />
          </div>

          <p v-if="clickupError" class="text-sm font-semibold text-red-300">{{ clickupError }}</p>

          <AppButton
            block
            icon="i-lucide-plug"
            :loading="setupLoading"
            :disabled="!apiToken || !workspaceId"
            @click="setupClickup"
          >
            Подключить ClickUp
          </AppButton>
        </div>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
const api = useApi()
const { user, haptic } = useTelegram()

const displayName = computed(() => {
  const fullName = [user?.first_name, user?.last_name].filter(Boolean).join(' ')
  return fullName || user?.username || 'Пользователь'
})
const tgUsername = computed(() => user?.username ?? '')
const initial = computed(() => (displayName.value[0] ?? '?').toUpperCase())

// Rate
const rateLoading = ref(true)
const rateSaving = ref(false)
const rateError = ref<string | null>(null)
const rateSuccess = ref(false)
const currentRate = ref(0)
const newRateStr = ref('')

// ClickUp
const clickupLoading = ref(true)
const clickupConfigured = ref(false)
const clickupUser = ref('')
const clickupWorkspace = ref('')
const clickupError = ref<string | null>(null)
const setupLoading = ref(false)
const resetLoading = ref(false)
const apiToken = ref('')
const workspaceId = ref('')

const saveRate = async () => {
  const rate = parseFloat(newRateStr.value)
  if (!rate || rate <= 0) return
  rateSaving.value = true
  rateError.value = null
  rateSuccess.value = false
  try {
    await api.put('/user/rate', { rate })
    currentRate.value = rate
    newRateStr.value = ''
    rateSuccess.value = true
    haptic.success()
    setTimeout(() => (rateSuccess.value = false), 3000)
  } catch (e: any) {
    rateError.value = e.message
    haptic.error()
  } finally {
    rateSaving.value = false
  }
}

const setupClickup = async () => {
  setupLoading.value = true
  clickupError.value = null
  try {
    const res = await api.post('/clickup/setup', {
      api_token: apiToken.value,
      workspace_id: workspaceId.value
    })
    clickupConfigured.value = true
    clickupUser.value = res.username ?? ''
    clickupWorkspace.value = workspaceId.value
    apiToken.value = ''
    workspaceId.value = ''
    haptic.success()
  } catch (e: any) {
    clickupError.value = e.message
    haptic.error()
  } finally {
    setupLoading.value = false
  }
}

const resetClickup = async () => {
  resetLoading.value = true
  clickupError.value = null
  try {
    await api.del('/clickup/setup')
    clickupConfigured.value = false
    clickupUser.value = ''
    clickupWorkspace.value = ''
    haptic.success()
  } catch (e: any) {
    clickupError.value = e.message
    haptic.error()
  } finally {
    resetLoading.value = false
  }
}

onMounted(async () => {
  const [rateRes, statusRes] = await Promise.all([
    api.get('/user/rate').catch(() => null),
    api.get('/clickup/status').catch(() => null)
  ])

  if (rateRes) currentRate.value = rateRes.rate ?? 0
  rateLoading.value = false

  if (statusRes?.configured) {
    clickupConfigured.value = true
    clickupUser.value = statusRes.username ?? ''
    clickupWorkspace.value = statusRes.workspace_id ?? ''
  }
  clickupLoading.value = false
})
</script>
