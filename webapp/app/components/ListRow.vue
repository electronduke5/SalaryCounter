<template>
  <button
    class="card flex w-full items-center gap-3 px-4 py-3.5 text-left transition-all active:scale-[0.985] active:bg-surface-2"
    @click="onClick"
  >
    <span
      v-if="icon"
      class="grid size-10 shrink-0 place-items-center rounded-xl bg-surface-2 text-acid"
    >
      <UIcon :name="icon" class="size-5" />
    </span>
    <span class="min-w-0 flex-1">
      <span class="block truncate text-[15px] font-semibold text-ink">{{ title }}</span>
      <span v-if="subtitle" class="mt-0.5 block truncate text-xs text-mist">{{ subtitle }}</span>
      <slot name="meta" />
    </span>
    <span v-if="trailing" class="shrink-0 text-sm font-bold tabular-nums text-ink">{{ trailing }}</span>
    <UIcon v-if="chevron" name="i-lucide-chevron-right" class="size-4 shrink-0 text-mist" />
  </button>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    subtitle?: string
    icon?: string
    trailing?: string
    chevron?: boolean
  }>(),
  { chevron: true }
)

const emit = defineEmits<{ click: [] }>()
const { haptic } = useTelegram()

const onClick = () => {
  haptic.impact('light')
  emit('click')
}
</script>
