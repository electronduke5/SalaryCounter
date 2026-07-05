export default defineNuxtConfig({
  ssr: false,
  modules: ['@nuxt/ui'],
  css: ['~/assets/css/main.css'],
  colorMode: {
    preference: 'dark',
    fallback: 'dark'
  },
  app: {
    pageTransition: { name: 'page', mode: 'out-in' },
    head: {
      title: 'SalaryCounter',
      // App is always dark; bake the class onto <html> so Nuxt UI components
      // (Popover/Calendar, portaled to <body>) theme dark before color-mode's JS runs.
      htmlAttrs: { lang: 'ru', class: 'dark' },
      meta: [
        {
          name: 'viewport',
          content: 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover'
        },
        { name: 'theme-color', content: '#0b0e13' }
      ],
      link: [
        { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
        { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
        {
          rel: 'stylesheet',
          href: 'https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Unbounded:wght@500;600;700;800&display=swap'
        }
      ],
      script: [{ src: 'https://telegram.org/js/telegram-web-app.js', tagPosition: 'head' }]
    }
  },
  runtimeConfig: {
    public: {
      apiBase: '/api/v1'
    }
  },
  vite: {
    server: {
      allowedHosts: ['.ngrok-free.app'],
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true
        }
      }
    }
  }
})
