<template>
  <button
    :disabled="disabled || loading"
    class="inline-flex items-center justify-center gap-2 rounded-2xl px-4 py-3 text-[15px] font-bold transition-all active:scale-[0.97] disabled:pointer-events-none disabled:opacity-40"
    :class="[variantClass, block ? 'w-full' : '']"
    @click="onClick"
  >
    <UIcon v-if="loading" name="i-lucide-loader-circle" class="size-4 animate-spin" />
    <UIcon v-else-if="icon" :name="icon" class="size-4" />
    <slot />
  </button>
</template>

<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'ghost' | 'danger'
    icon?: string
    loading?: boolean
    disabled?: boolean
    block?: boolean
  }>(),
  { variant: 'primary' }
)

const emit = defineEmits<{ click: [] }>()
const { haptic } = useTelegram()

const variantClass = computed(() => {
  switch (props.variant) {
    case 'ghost':
      return 'bg-surface-2 text-ink border border-edge'
    case 'danger':
      return 'bg-red-500/12 text-red-300 border border-red-500/25'
    default:
      return 'bg-acid text-[#0d1206] shadow-[0_10px_28px_-10px_rgba(198,244,85,0.55)]'
  }
})

const onClick = () => {
  haptic.impact('light')
  emit('click')
}
</script>
