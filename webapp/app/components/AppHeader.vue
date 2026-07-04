<template>
  <header class="pt-1 pb-5 reveal">
    <div class="flex items-center gap-3">
      <button
        v-if="back && !isTelegram"
        class="grid size-9 shrink-0 place-items-center rounded-full bg-surface-2 border border-edge text-ink transition active:scale-90"
        aria-label="Назад"
        @click="goBack"
      >
        <UIcon name="i-lucide-arrow-left" class="size-4" />
      </button>
      <div class="min-w-0 flex-1">
        <p v-if="kicker" class="mb-1 text-[11px] font-bold uppercase tracking-[0.18em] text-mist">
          {{ kicker }}
        </p>
        <h1 class="truncate font-display text-[21px] font-semibold leading-tight text-ink">
          {{ title }}
        </h1>
        <p v-if="subtitle" class="mt-0.5 truncate text-sm text-mist">{{ subtitle }}</p>
      </div>
      <slot name="trailing" />
    </div>
  </header>
</template>

<script setup lang="ts">
const props = defineProps<{
  title: string
  subtitle?: string
  kicker?: string
  back?: boolean
}>()

const router = useRouter()
const { tg, isTelegram, haptic } = useTelegram()

const goBack = () => {
  haptic.impact('light')
  router.back()
}

onMounted(() => {
  if (props.back && isTelegram) {
    tg.BackButton.show()
    tg.BackButton.onClick(goBack)
  }
})

onUnmounted(() => {
  if (props.back && isTelegram) {
    tg.BackButton.offClick(goBack)
    tg.BackButton.hide()
  }
})
</script>
