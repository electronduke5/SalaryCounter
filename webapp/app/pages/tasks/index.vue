<template>
  <div class="page">
    <AppHeader kicker="Задачи" title="Пространства" subtitle="Выберите рабочее пространство" />

    <div v-if="loading" class="space-y-2">
      <SkeletonBlock v-for="i in 4" :key="i" height="4.25rem" radius="1.375rem" />
    </div>

    <div v-else-if="error" class="card reveal border-red-500/25 bg-red-500/8 p-4">
      <p class="mb-3 text-sm font-semibold text-red-300">{{ error }}</p>
      <AppButton variant="ghost" icon="i-lucide-rotate-cw" @click="loadSpaces">Повторить</AppButton>
    </div>

    <EmptyState
      v-else-if="spaces.length === 0"
      class="reveal"
      icon="i-lucide-layout-grid"
      title="Нет доступных пространств"
      hint="Подключите ClickUp в разделе Настройки"
    >
      <AppButton variant="ghost" icon="i-lucide-settings" @click="router.push('/settings')">
        Настройки
      </AppButton>
    </EmptyState>

    <div v-else class="space-y-2">
      <ListRow
        v-for="(space, i) in spaces"
        :key="space.id"
        class="reveal"
        :style="{ animationDelay: `${i * 45}ms` }"
        icon="i-lucide-layout-grid"
        :title="space.name"
        @click="router.push(`/tasks/${space.id}`)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
const api = useApi()
const router = useRouter()

const loading = ref(true)
const error = ref<string | null>(null)
const spaces = ref<any[]>([])

const loadSpaces = async () => {
  loading.value = true
  error.value = null
  try {
    const res = await api.get('/clickup/spaces')
    spaces.value = res.spaces ?? res ?? []
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(loadSpaces)
</script>
