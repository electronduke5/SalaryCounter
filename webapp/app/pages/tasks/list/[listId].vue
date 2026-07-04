<template>
  <div class="page">
    <AppHeader back kicker="Список" :title="listName" />

    <SegmentedControl v-model="activeStatus" :options="statusFilters" class="reveal mb-4" />

    <div v-if="loading" class="space-y-2">
      <SkeletonBlock v-for="i in 5" :key="i" height="4.5rem" radius="1.375rem" />
    </div>

    <div v-else-if="error" class="card reveal border-red-500/25 bg-red-500/8 p-4">
      <p class="mb-3 text-sm font-semibold text-red-300">{{ error }}</p>
      <AppButton variant="ghost" icon="i-lucide-rotate-cw" @click="loadTasks">Повторить</AppButton>
    </div>

    <EmptyState
      v-else-if="filteredTasks.length === 0"
      class="reveal"
      icon="i-lucide-check-check"
      title="Нет задач"
      hint="С выбранным статусом задач не найдено"
    />

    <div v-else class="space-y-2">
      <ListRow
        v-for="(task, i) in filteredTasks"
        :key="task.id"
        class="reveal"
        :style="{ animationDelay: `${Math.min(i, 8) * 40}ms` }"
        :title="task.name"
        @click="router.push(`/task/${task.id}`)"
      >
        <template #meta>
          <span class="mt-1.5 flex flex-wrap items-center gap-2">
            <StatusBadge :status="task.status?.status ?? task.status" />
            <span v-if="task.due_date" class="inline-flex items-center gap-1 text-[11px] font-semibold text-mist">
              <UIcon name="i-lucide-calendar" class="size-3" />
              {{ formatDue(task.due_date) }}
            </span>
          </span>
        </template>
      </ListRow>
    </div>
  </div>
</template>

<script setup lang="ts">
const api = useApi()
const router = useRouter()
const route = useRoute()

const listId = computed(() => route.params.listId as string)
const listName = ref('Задачи')
const loading = ref(true)
const error = ref<string | null>(null)
const tasks = ref<any[]>([])
const activeStatus = ref('all')

const statusFilters = [
  { value: 'all', label: 'Все' },
  { value: 'open', label: 'Open' },
  { value: 'in progress', label: 'In Progress' },
  { value: 'review', label: 'Review' },
  { value: 'done', label: 'Done' },
  { value: 'complete', label: 'Complete' }
]

const filteredTasks = computed(() => {
  if (activeStatus.value === 'all') return tasks.value
  return tasks.value.filter(t => {
    const s = (t.status?.status ?? t.status ?? '').toLowerCase()
    return s === activeStatus.value
  })
})

const formatDue = (ts: string | number) => {
  const d = new Date(typeof ts === 'string' ? ts : Number(ts))
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

const loadTasks = async () => {
  loading.value = true
  error.value = null
  try {
    const res = await api.get(`/clickup/lists/${listId.value}/tasks?status=all`)
    tasks.value = res.tasks ?? res ?? []
    listName.value = res.list_name ?? 'Задачи'
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(loadTasks)
</script>
