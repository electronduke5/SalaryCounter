<template>
  <nav
    class="pointer-events-none fixed inset-x-0 bottom-0 z-50 px-4 pt-2"
    style="padding-bottom: max(env(safe-area-inset-bottom), 12px)"
  >
    <div
      class="pointer-events-auto mx-auto flex max-w-lg rounded-[1.375rem] border border-edge bg-surface/85 shadow-2xl shadow-black/50 backdrop-blur-xl"
    >
      <NuxtLink
        v-for="tab in tabs"
        :key="tab.to"
        :to="tab.to"
        class="flex flex-1 flex-col items-center gap-1 py-2.5 transition-colors"
        :class="isActive(tab) ? 'text-acid' : 'text-mist'"
        @click="haptic.select()"
      >
        <UIcon :name="tab.icon" class="size-5" />
        <span class="text-[10px] font-bold">{{ tab.label }}</span>
      </NuxtLink>
    </div>
  </nav>
</template>

<script setup lang="ts">
const route = useRoute()
const { haptic } = useTelegram()

const tabs = [
  { to: '/', icon: 'i-lucide-house', label: 'Главная' },
  { to: '/earnings', icon: 'i-lucide-chart-column', label: 'Отчёты' },
  { to: '/tasks', icon: 'i-lucide-list-checks', label: 'Задачи' },
  { to: '/analytics', icon: 'i-lucide-chart-pie', label: 'Аналитика' },
  { to: '/settings', icon: 'i-lucide-settings', label: 'Настройки' }
]

const isActive = (tab: { to: string }) => {
  if (tab.to === '/') return route.path === '/'
  // Task detail pages belong to the tasks tab
  if (tab.to === '/tasks') return route.path.startsWith('/tasks') || route.path.startsWith('/task/')
  return route.path.startsWith(tab.to)
}
</script>
