<template>
  <div class="skeleton" :style="{ height, borderRadius: radius }" />
</template>

<script setup lang="ts">
withDefaults(defineProps<{ height?: string; radius?: string }>(), {
  height: '3rem',
  radius: '0.875rem'
})
</script>
