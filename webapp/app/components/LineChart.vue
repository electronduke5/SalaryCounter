<template>
  <div ref="wrap" class="card px-3 pb-2 pt-3">
    <!-- Legend -->
    <div v-if="previous?.length" class="mb-2 flex items-center justify-end gap-3 text-[10px] font-bold">
      <span class="flex items-center gap-1 text-acid">
        <span class="h-0.5 w-3 rounded-full bg-acid" />
        {{ currentLabel || 'сейчас' }}
      </span>
      <span class="flex items-center gap-1 text-mist">
        <span class="h-0.5 w-3 rounded-full bg-mist" />
        {{ previousLabel || 'прошлый' }}
      </span>
    </div>

    <div class="relative">
      <svg
        ref="svgEl"
        :width="width"
        :height="height"
        class="block touch-pan-y select-none overflow-visible text-acid"
        @pointerdown="onPointer"
        @pointermove="onPointer"
        @pointerup="clear"
        @pointerleave="clear"
        @pointercancel="clear"
      >
        <defs>
          <linearGradient :id="gid" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="currentColor" stop-opacity="0.24" />
            <stop offset="100%" stop-color="currentColor" stop-opacity="0" />
          </linearGradient>
        </defs>

        <!-- Scrub guide -->
        <line
          v-if="activeIndex !== null"
          :x1="activeX"
          y1="0"
          :x2="activeX"
          :y2="baseY"
          stroke="var(--color-edge)"
          stroke-width="1"
        />

        <!-- Previous period: muted dashed line -->
        <path
          v-if="prevPath"
          :d="prevPath"
          fill="none"
          stroke="var(--color-mist)"
          stroke-width="1.5"
          stroke-dasharray="3 3"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <circle
          v-for="p in prevPoints"
          :key="`p${p.key}`"
          :cx="p.x"
          :cy="p.y"
          r="2"
          fill="var(--color-mist)"
        />

        <!-- Current period: acid line + area fill -->
        <path v-if="curArea" :d="curArea" :fill="`url(#${gid})`" />
        <path
          v-if="curPath"
          :d="curPath"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <circle
          v-for="p in curPoints"
          :key="`c${p.key}`"
          :cx="p.x"
          :cy="p.y"
          r="3"
          fill="currentColor"
        />

        <!-- Active highlight rings -->
        <circle
          v-if="activePrev"
          :cx="activeX"
          :cy="activePrev.y"
          r="4"
          fill="var(--color-surface)"
          stroke="var(--color-mist)"
          stroke-width="2"
        />
        <circle
          v-if="activeCur"
          :cx="activeX"
          :cy="activeCur.y"
          r="4.5"
          fill="var(--color-surface)"
          stroke="currentColor"
          stroke-width="2"
        />
      </svg>

      <!-- Tooltip -->
      <div
        v-if="activeIndex !== null"
        class="pointer-events-none absolute top-0 z-10 w-[150px] rounded-xl border border-edge bg-surface/95 p-2.5 shadow-lg backdrop-blur"
        :style="{ left: `${tipLeft}px` }"
      >
        <div class="mb-1.5 text-[11px] font-bold text-ink">{{ labels[activeIndex] }}</div>
        <div class="space-y-1.5">
          <div v-for="row in tipRows" :key="row.name">
            <div class="flex items-center gap-1.5">
              <span class="size-1.5 rounded-full" :class="row.current ? 'bg-acid' : 'bg-mist'" />
              <span class="text-[10px] font-semibold text-mist">{{ row.name }}</span>
            </div>
            <div class="pl-3 text-[11px] font-bold tabular-nums text-ink">{{ fmtRow(row.data) }}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="mt-1.5 flex gap-1">
      <div
        v-for="(label, i) in axisLabels"
        :key="i"
        class="min-w-0 flex-1 overflow-visible whitespace-nowrap text-center text-[10px] font-semibold capitalize"
        :class="i === activeIndex ? 'text-acid' : 'text-mist'"
      >
        {{ label }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
interface PointData {
  hours: number
  earnings: number
}

const props = withDefaults(
  defineProps<{
    labels: string[]
    current: (PointData | null)[]
    previous?: (PointData | null)[]
    // Which metric drives the curve height (tooltip always shows both).
    field?: 'earnings' | 'hours'
    currentLabel?: string
    previousLabel?: string
  }>(),
  { field: 'earnings' }
)

const gid = useId()
const height = 140
const padTop = 12
const padBottom = 6
const baseY = height - padBottom

const wrap = ref<HTMLElement | null>(null)
const svgEl = ref<SVGGraphicsElement | null>(null)
const width = ref(320)
let ro: ResizeObserver | null = null

onMounted(() => {
  const el = wrap.value
  if (!el) return
  // clientWidth includes the card's horizontal padding (px-3 → 12px each side).
  const measure = () => (width.value = Math.max(el.clientWidth - 24, 1))
  measure()
  ro = new ResizeObserver(measure)
  ro.observe(el)
})
onUnmounted(() => ro?.disconnect())

const n = computed(() => props.labels.length)

// Thin dense axes (e.g. ~31 days) so labels don't collide: show ~every Nth,
// plus the last tick and whatever is being scrubbed. Empty slots keep alignment.
const axisLabels = computed(() => {
  const total = props.labels.length
  const stride = Math.max(1, Math.ceil(total / 12))
  return props.labels.map((l, i) =>
    i % stride === 0 || i === total - 1 || i === activeIndex.value ? l : ''
  )
})

const max = computed(() =>
  Math.max(
    ...props.current.map(v => (v ? v[props.field] : 0)),
    ...(props.previous ?? []).map(v => (v ? v[props.field] : 0)),
    0.01
  )
)

const binX = (i: number) => (n.value <= 1 ? width.value / 2 : ((i + 0.5) / n.value) * width.value)
const scaleY = (v: number) => padTop + (baseY - padTop) * (1 - v / max.value)

const toPoints = (arr: (PointData | null)[]) =>
  arr
    .map((v, i) => (v == null ? null : { key: i, x: binX(i), y: scaleY(v[props.field]) }))
    .filter((p): p is { key: number; x: number; y: number } => p !== null)

const curPoints = computed(() => toPoints(props.current))
const prevPoints = computed(() => toPoints(props.previous ?? []))

// Catmull-Rom → cubic bezier for a smooth curve through every point.
const smoothPath = (pts: { x: number; y: number }[]): string => {
  if (pts.length < 2) return ''
  let d = `M ${pts[0].x} ${pts[0].y}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] ?? p2
    const cp1x = p1.x + (p2.x - p0.x) / 6
    const cp1y = p1.y + (p2.y - p0.y) / 6
    const cp2x = p2.x - (p3.x - p1.x) / 6
    const cp2y = p2.y - (p3.y - p1.y) / 6
    d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2.x} ${p2.y}`
  }
  return d
}

const curPath = computed(() => smoothPath(curPoints.value))
const prevPath = computed(() => smoothPath(prevPoints.value))

const curArea = computed(() => {
  const p = curPoints.value
  if (p.length < 2) return ''
  return `${smoothPath(p)} L ${p[p.length - 1].x} ${baseY} L ${p[0].x} ${baseY} Z`
})

// --- Scrub interaction ---
const activeIndex = ref<number | null>(null)

const onPointer = (e: PointerEvent) => {
  const el = svgEl.value
  if (!el || !n.value) return
  if (e.type === 'pointerdown') el.setPointerCapture?.(e.pointerId)
  const rect = el.getBoundingClientRect()
  const x = e.clientX - rect.left
  activeIndex.value = Math.min(n.value - 1, Math.max(0, Math.round((x / width.value) * n.value - 0.5)))
}
const clear = () => (activeIndex.value = null)

const activeX = computed(() => (activeIndex.value === null ? 0 : binX(activeIndex.value)))

const activeAt = (arr: (PointData | null)[]) => {
  const i = activeIndex.value
  if (i === null) return null
  const v = arr[i]
  return v == null ? null : { y: scaleY(v[props.field]) }
}
const activeCur = computed(() => activeAt(props.current))
const activePrev = computed(() => activeAt(props.previous ?? []))

const tipRows = computed(() => {
  const i = activeIndex.value
  if (i === null) return []
  const rows = [{ name: props.currentLabel || 'сейчас', current: true, data: props.current[i] ?? null }]
  if (props.previous?.length) {
    rows.push({ name: props.previousLabel || 'прошлый', current: false, data: props.previous[i] ?? null })
  }
  return rows
})

const fmtRow = (d: PointData | null) =>
  d ? `${formatHoursLabel(d.hours)} · ${formatMoney(d.earnings)} ₽` : '—'

// Keep the tooltip inside the chart bounds.
const tipLeft = computed(() => Math.min(Math.max(activeX.value - 75, 0), Math.max(width.value - 150, 0)))
</script>
