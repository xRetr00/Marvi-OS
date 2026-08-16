/**
 * Electric Gaze — animated ASCII backdrop behind the control center. The
 * video asset is vendored locally (assets/background/electric-gaze.mp4,
 * 412 KB, CC0-style 21st.dev ascii-recipe render) so the shell never depends
 * on a CDN; source URL recorded in docs/UPSTREAM.md. Opacity and on/off are
 * user settings via the background store. Pattern adapted from the Hermes
 * desktop background store + Backdrop component (MIT).
 */
import { useStore } from '@nanostores/react'

import gazePoster from '../assets/background/electric-gaze-poster.webp'
import gazeVideo from '../assets/background/electric-gaze.mp4'
import { $backgroundMode, $backgroundOpacity } from '../store/background'

export function ElectricGazeBackground(): React.JSX.Element | null {
  const mode = useStore($backgroundMode)
  const opacity = useStore($backgroundOpacity)

  if (mode !== 'electricGaze') return null

  return (
    <div aria-hidden="true" className="electric-gaze">
      <video
        autoPlay
        className="electric-gaze-video"
        loop
        muted
        playsInline
        poster={gazePoster}
        src={gazeVideo}
        style={{ opacity: opacity / 100 }}
      />
    </div>
  )
}
