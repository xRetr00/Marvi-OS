/**
 * Block-element loading indicator: the █ ▓ ▒ blocks slide over a ░ track like
 * an accordion, with staggered timing so the three densities read as one
 * sweeping weight. Adapted from a user-provided `AccordionLoader` example
 * (shadcn/Tailwind style) — de-Tailwind-ed onto Marvi's plain CSS and design
 * tokens. The glyphs are Unicode Block Elements (U+2588/U+2593/U+2592/U+2591).
 */

const DEFAULT_BLOCKS = ['█', '▓', '▒'] as const

interface AccordionLoaderProps extends React.ComponentProps<'span'> {
  blocks?: readonly string[]
  track?: string
  trackLength?: number
}

export function AccordionLoader({
  className,
  blocks = DEFAULT_BLOCKS,
  track = '░',
  trackLength = 16,
  style,
  ...props
}: AccordionLoaderProps): React.JSX.Element {
  const columns = Math.max(2, Math.floor(trackLength))
  const glyphs = DEFAULT_BLOCKS.map((_, index) => blocks[index] ?? DEFAULT_BLOCKS[index])

  return (
    <span
      role="status"
      className={`accordion-loader${className ? ` ${className}` : ''}`}
      style={
        {
          '--loader-width': `${columns}ch`,
          '--loader-x': `${columns - 1}ch`,
          ...style
        } as React.CSSProperties
      }
      {...props}
    >
      <span aria-hidden="true" className="accordion-loader-track">
        {track.repeat(columns)}
      </span>
      {glyphs.map((glyph, index) => (
        <span
          key={`${glyph}-${index}`}
          aria-hidden="true"
          className={`accordion-loader-block accordion-loader-block-${index}`}
          style={{
            animation: 'accordion-loader-slide var(--duration, 2.8s) ease-in-out infinite',
            animationDelay: `calc(var(--delay, 0.04s) * ${index})`
          }}
        >
          {glyph}
        </span>
      ))}
      <span className="sr-only">Loading</span>
    </span>
  )
}

export default AccordionLoader
