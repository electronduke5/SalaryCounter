<template>
  <div class="no-scrollbar -mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1">
    <button
      v-for="opt in options"
      :key="opt.value"
      class="whitespace-nowrap rounded-full px-3.5 py-2 text-[13px] font-bold transition-all active:scale-95"
      :class="
        modelValue === opt.value
          ? 'bg-acid text-[#0d1206]'
          : 'bg-surface-2 text-mist border border-edge'
      "
      @click="select(opt.value)"
    >
      {{ opt.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  modelValue: string
  options: { value: string; label: string }[]
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const { haptic } = useTelegram()

const select = (value: string) => {
  haptic.select()
  emit('update:modelValue', value)
}
</script>
