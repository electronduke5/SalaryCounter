<template>
  <UApp :locale="ru">
    <div class="grain" aria-hidden="true" />
    <NuxtPage />
    <NavigationBar />
  </UApp>
</template>

<script setup lang="ts">
import { ru } from '@nuxt/ui/locale'

const { ready, expand, setChrome } = useTelegram()

onMounted(() => {
  ready()
  expand()
  setChrome('#0b0e13')
})
</script>
