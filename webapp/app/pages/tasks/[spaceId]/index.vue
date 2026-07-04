<template>
  <div class="page">
    <AppHeader back kicker="Пространство" :title="spaceName" />

    <div v-if="loading" class="space-y-2">
      <SkeletonBlock v-for="i in 4" :key="i" height="4.25rem" radius="1.375rem" />
    </div>

    <div v-else-if="error" class="card reveal border-red-500/25 bg-red-500/8 p-4">
      <p class="mb-3 text-sm font-semibold text-red-300">{{ error }}</p>
      <AppButton variant="ghost" icon="i-lucide-rotate-cw" @click="loadData">Повторить</AppButton>
    </div>

    <template v-else>
      <!-- Folders -->
      <section v-if="folders.length" class="mb-5">
        <h2 class="mb-2.5 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">Папки</h2>
        <div class="space-y-2">
          <ListRow
            v-for="(folder, i) in folders"
            :key="folder.id"
            class="reveal"
            :style="{ animationDelay: `${i * 45}ms` }"
            icon="i-lucide-folder"
            :title="folder.name"
            @click="router.push(`/tasks/${spaceId}/${folder.id}`)"
          />
        </div>
      </section>

      <!-- Root lists -->
      <section v-if="rootLists.length">
        <h2 class="mb-2.5 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">Списки</h2>
        <div class="space-y-2">
          <ListRow
            v-for="(list, i) in rootLists"
            :key="list.id"
            class="reveal"
            :style="{ animationDelay: `${(folders.length + i) * 45}ms` }"
            icon="i-lucide-list"
            :title="list.name"
            @click="router.push(`/tasks/list/${list.id}`)"
          />
        </div>
      </section>

      <EmptyState
        v-if="!folders.length && !rootLists.length"
        class="reveal"
        icon="i-lucide-folder-open"
        title="Здесь пусто"
        hint="В этом пространстве нет папок и списков"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
const api = useApi()
const router = useRouter()
const route = useRoute()

const spaceId = computed(() => route.params.spaceId as string)
const spaceName = ref('Пространство')
const loading = ref(true)
const error = ref<string | null>(null)
const folders = ref<any[]>([])
const rootLists = ref<any[]>([])

const loadData = async () => {
  loading.value = true
  error.value = null
  try {
    const res = await api.get(`/clickup/spaces/${spaceId.value}/folders`)
    folders.value = res.folders ?? []
    rootLists.value = res.root_lists ?? []
    spaceName.value = res.space_name ?? 'Пространство'
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>
