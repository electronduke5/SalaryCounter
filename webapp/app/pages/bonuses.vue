<template>
  <div class="page">
    <AppHeader kicker="Премии" :title="`${year} год`" />

    <template v-if="loading">
      <SkeletonBlock height="8rem" radius="1.375rem" class="mb-4" />
      <SkeletonBlock height="12rem" radius="1.375rem" />
    </template>

    <template v-else>
      <!-- Add form -->
      <section class="card reveal mb-4 p-5">
        <h2 class="mb-4 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">
          <UIcon name="i-lucide-gift" class="size-4" />
          Добавить премию
        </h2>
        <div class="space-y-3">
          <div class="flex gap-2">
            <input
              v-model="amountStr"
              type="number"
              min="0"
              inputmode="numeric"
              placeholder="Сумма, ₽"
              class="field flex-1"
              :disabled="saving"
            />
            <input v-model="date" type="date" class="field w-40" :disabled="saving" />
          </div>
          <input
            v-model="comment"
            type="text"
            placeholder="Комментарий (например, Q2)"
            class="field"
            :disabled="saving"
          />
          <p v-if="formError" class="text-sm font-semibold text-red-300">{{ formError }}</p>
          <AppButton block icon="i-lucide-plus" :loading="saving" :disabled="!amountStr" @click="addBonus">
            Добавить
          </AppButton>
        </div>
      </section>

      <!-- List -->
      <section class="reveal" style="animation-delay: 60ms">
        <div class="mb-2.5 flex items-baseline justify-between">
          <h2 class="text-[11px] font-bold uppercase tracking-[0.18em] text-mist">Выплаты</h2>
          <span v-if="bonuses.length" class="font-display text-sm font-bold tabular-nums text-acid">
            {{ formatMoney(total) }} ₽
          </span>
        </div>

        <div v-if="bonuses.length" class="space-y-2">
          <div
            v-for="b in bonuses"
            :key="b.id"
            class="card flex items-center gap-3 px-4 py-3.5"
          >
            <span class="grid size-10 shrink-0 place-items-center rounded-xl bg-surface-2 text-acid">
              <UIcon name="i-lucide-gift" class="size-5" />
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[15px] font-semibold text-ink">
                {{ formatMoney(b.amount) }} ₽
              </span>
              <span class="mt-0.5 block truncate text-xs text-mist">
                {{ formatDayLabel(b.date) }}<template v-if="b.comment"> · {{ b.comment }}</template>
              </span>
            </span>
            <button
              class="grid size-9 shrink-0 place-items-center rounded-xl text-mist transition-colors active:bg-surface-2 active:text-red-300"
              :disabled="deletingId === b.id"
              @click="deleteBonus(b.id)"
            >
              <UIcon
                :name="deletingId === b.id ? 'i-lucide-loader-circle' : 'i-lucide-trash-2'"
                class="size-4.5"
                :class="deletingId === b.id ? 'animate-spin' : ''"
              />
            </button>
          </div>
        </div>

        <EmptyState
          v-else
          icon="i-lucide-gift"
          title="Премий пока нет"
          hint="Добавьте квартальную премию — она учтётся в месячном итоге и прогрессе к цели"
        />
      </section>

      <div v-if="error" class="card reveal mt-4 border-red-500/25 bg-red-500/8 p-4">
        <p class="text-sm font-semibold text-red-300">{{ error }}</p>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
const api = useApi()
const { haptic } = useTelegram()

const year = new Date().getFullYear()
const loading = ref(true)
const saving = ref(false)
const deletingId = ref<number | null>(null)
const error = ref<string | null>(null)
const formError = ref<string | null>(null)

const bonuses = ref<Array<{ id: number; date: string; amount: number; comment: string | null }>>([])
const total = ref(0)

const amountStr = ref('')
const date = ref(new Date().toISOString().slice(0, 10))
const comment = ref('')

const load = async () => {
  const data = await api.get(`/bonuses?year=${year}`)
  bonuses.value = data.bonuses
  total.value = data.total
}

const addBonus = async () => {
  const amount = parseFloat(amountStr.value)
  if (!amount || amount <= 0) {
    formError.value = 'Введите положительную сумму'
    return
  }
  saving.value = true
  formError.value = null
  try {
    await api.post('/bonuses', {
      date: date.value,
      amount,
      comment: comment.value.trim() || null
    })
    amountStr.value = ''
    comment.value = ''
    await load()
    haptic.success()
  } catch (e: any) {
    formError.value = e.message
    haptic.error()
  } finally {
    saving.value = false
  }
}

const deleteBonus = async (id: number) => {
  deletingId.value = id
  error.value = null
  try {
    await api.del(`/bonuses/${id}`)
    await load()
    haptic.success()
  } catch (e: any) {
    error.value = e.message
    haptic.error()
  } finally {
    deletingId.value = null
  }
}

onMounted(async () => {
  try {
    await load()
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})
</script>
