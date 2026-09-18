/**
 * What a picture being drawn looks like while it is being drawn.
 *
 * Image generation takes several seconds and produces nothing until it
 * produces everything, so the ordinary tool step -- a name and a spinner --
 * says almost nothing about a wait that long. This stands in for the image at
 * the size it will be, with the prompt underneath, so the wait looks like the
 * thing you asked for arriving rather than the window having stopped.
 *
 * Supplied by the owner as `ImageGeneration`; adapted here to Marvi's
 * monochrome tokens, and to stop moving when the machine asks it to.
 */
export function ImageGeneration({
  prompt = 'a calm mountain lake at dawn',
  resolution = '1024 × 1024'
}: {
  prompt?: string
  resolution?: string
}): React.JSX.Element {
  return (
    <div className="igWrap">
      <div className="igCanvas" role="img" aria-label={`Generating an image of ${prompt}`}>
        <span className="igDots" aria-hidden />
        <span className="igGlow" aria-hidden />
        <span className="igRes">{resolution}</span>
      </div>
      <div className="igMeta">
        <span className="igLabel">Generating image</span>
        <span className="igPrompt">“{prompt}”</span>
      </div>
    </div>
  )
}

/** `1024x1024` as the size a person reads. Anything unexpected is left alone. */
export function prettySize(size: unknown): string {
  const raw = typeof size === 'string' ? size.trim() : ''
  const match = /^(\d+)\s*[x×]\s*(\d+)$/i.exec(raw)
  return match ? `${match[1]} × ${match[2]}` : raw || '1024 × 1024'
}

export default ImageGeneration
