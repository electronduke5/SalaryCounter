<template>
  <div class="page">
    <AppHeader back kicker="Папка" :title="folderName" subtitle="Выберите список" />

    <div v-if="loading" class="space-y-2">
      <SkeletonBlock v-for="i in 4" :key="i" height="4.25rem" radius="1.375rem" />
    </div>

    <div v-else-if="error" class="card reveal border-red-500/25 bg-red-500/8 p-4">
      <p class="mb-3 text-sm font-semibold text-red-300">{{ error }}</p>
      <AppButton variant="ghost" icon="i-lucide-rotate-cw" @click="loadLists">Повторить</AppButton>
    </div>

    <EmptyState
      v-else-if="lists.length === 0"
      class="reveal"
      icon="i-lucide-list-x"
      title="Нет списков"
      hint="В этой папке пока нет списков задач"
    />

    <div v-else class="space-y-2">
      <ListRow
        v-for="(list, i) in lists"
        :key="list.id"
        class="reveal"
        :style="{ animationDelay: `${i * 45}ms` }"
        icon="i-lucide-list"
        :title="list.name"
        :subtitle="list.task_count !== undefined ? `${list.task_count} задач` : undefined"
        @click="router.push(`/tasks/list/${list.id}`)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
const api = useApi()
const router = useRouter()
const route = useRoute()

const spaceId = computed(() => route.params.spaceId as string)
const folderId = computed(() => route.params.folderId as string)
const folderName = ref('Папка')
const loading = ref(true)
const error = ref<string | null>(null)
const lists = ref<any[]>([])

const loadLists = async () => {
  loading.value = true
  error.value = null
  try {
    const res = await api.get(`/clickup/folders/${folderId.value}/lists?space_id=${spaceId.value}`)
    lists.value = res.lists ?? res ?? []
    folderName.value = res.folder_name ?? 'Папка'
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(loadLists)
</script>
