<template>
  <div class="card reveal flex flex-col items-center px-6 py-10 text-center">
    <div class="mb-4 grid size-14 place-items-center rounded-2xl bg-surface-2 text-mist">
      <UIcon :name="icon" class="size-7" />
    </div>
    <p class="font-display text-[15px] font-semibold text-ink">{{ title }}</p>
    <p v-if="hint" class="mt-1.5 max-w-[24ch] text-[13px] leading-relaxed text-mist">{{ hint }}</p>
    <div v-if="$slots.default" class="mt-4">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ icon?: string; title: string; hint?: string }>(), {
  icon: 'i-lucide-inbox'
})
</script>
