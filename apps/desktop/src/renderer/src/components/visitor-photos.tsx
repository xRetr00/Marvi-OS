/**
 * The photographs of somebody who was in the room while you were not.
 *
 * This is the end of a chain that starts minutes earlier: OwnTracks says the
 * phone is elsewhere, mmWave says a person is in the room, the camera cannot
 * name a face, and the sidecar decides that is a stranger rather than an owner
 * whose phone went flat. It photographs them three times, ten seconds apart,
 * at the sensor's full resolution -- and until now that was where it stopped,
 * because nothing showed you the pictures.
 *
 * Three frames rather than one for a mundane reason: the single frame taken as
 * somebody walks in is very often the back of their head. Ten seconds apart
 * covers turning round, sitting down and looking up, and one of the three
 * usually has a face in it.
 *
 * ## Times are shown where you are
 *
 * The sidecar records UTC with an explicit offset, which is correct and reads
 * as wrong: a photograph taken at one in the morning is stamped `22:00Z`, and
 * the owner's first reaction to that is that the camera's clock is broken. So
 * every time here is rendered in the machine's own zone, with the date, because
 * "when was somebody in my room" is the entire question.
 *
 * ## Seen, or later
 *
 * The photographs are for one look. **Seen** deletes them; **See later** (and
 * closing, which is the same decision made less carefully) brings the popup
 * back in an hour. Before this they stayed on disk forever -- 249 of them in
 * a month -- because closing the popup was the only way out of it.
 */
import { Camera, ChevronLeft, ChevronRight, Clock, X } from 'lucide-react'
import React, { useEffect, useState } from 'react'

export interface VisitorPhoto {
  at: string
  path: string
  index: number
  width?: number
  height?: number
}

export interface VisitorSighting {
  id: number
  at: string
  /** `unknown_visitor`, `unidentified`, `guest`. */
  classification?: string
  identity_reason?: string
  /** False when the burst was taken in the dark because sleep mode was on. */
  lit?: boolean
  photos: VisitorPhoto[]
}

/** The machine's own zone, with the date, because that is the question. */
function localMoment(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return iso
  return at.toLocaleString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

/** Why the sidecar could not name them, in words. */
function explain(sighting: VisitorSighting): string {
  const why = sighting.identity_reason ?? ''
  if (why.includes('battery')) {
    const percent = /(\d+)/.exec(why)?.[1]
    return `Their phone was at ${percent ?? 'a low'}% and went quiet, so this may still be you.`
  }
  if (why.includes('stale')) return 'The phone had not reported in long enough to mean anything.'
  if (why === 'owner_phone_away') return 'Your phone was somewhere else at the time.'
  if (why.includes('without_recent_owner')) return 'Nothing recent identified them as you.'
  return why.replaceAll('_', ' ')
}

export function VisitorPhotos({
  sighting,
  onSeen,
  onLater
}: {
  sighting: VisitorSighting
  /** Delete the photographs. */
  onSeen: () => void
  /** Keep them and ask again later. Also what closing does. */
  onLater: () => void
}): React.JSX.Element {
  const onClose = onLater
  const [shown, setShown] = useState(0)
  const photos = sighting.photos ?? []
  const photo = photos[Math.min(shown, photos.length - 1)]

  // Escape closes, arrows step. A modal that traps you is worse than no modal.
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
      if (event.key === 'ArrowRight') setShown((n) => Math.min(n + 1, photos.length - 1))
      if (event.key === 'ArrowLeft') setShown((n) => Math.max(n - 1, 0))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, photos.length])

  const stranger = sighting.classification === 'unknown_visitor'

  return (
    <div className="vis-backdrop" onClick={onClose} role="presentation">
      <div
        aria-label="Photographs of a visitor"
        className="vis-modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header className="vis-head">
          <div>
            <h2>{stranger ? 'Someone was in your room' : 'Someone came in'}</h2>
            <p>
              <Clock aria-hidden="true" />
              {localMoment(sighting.at)}
            </p>
          </div>
          <button aria-label="Close" onClick={onClose} type="button">
            <X aria-hidden="true" />
          </button>
        </header>

        <p className="vis-why">{explain(sighting)}</p>

        {photos.length === 0 ? (
          <p className="vis-empty">
            <Camera aria-hidden="true" /> No photographs were taken.
          </p>
        ) : (
          <>
            <div className="vis-frame">
              {/* `file://` because these never leave the machine. */}
              <img alt={`Visitor at ${localMoment(photo.at)}`} src={`file://${photo.path}`} />
              {photos.length > 1 && (
                <>
                  <button
                    aria-label="Previous photograph"
                    className="vis-step is-back"
                    disabled={shown === 0}
                    onClick={() => setShown((n) => Math.max(n - 1, 0))}
                    type="button"
                  >
                    <ChevronLeft aria-hidden="true" />
                  </button>
                  <button
                    aria-label="Next photograph"
                    className="vis-step is-next"
                    disabled={shown >= photos.length - 1}
                    onClick={() => setShown((n) => Math.min(n + 1, photos.length - 1))}
                    type="button"
                  >
                    <ChevronRight aria-hidden="true" />
                  </button>
                </>
              )}
            </div>

            <footer className="vis-foot">
              <span className="vis-stamp">
                {localMoment(photo.at)}
                {photo.width ? ` · ${photo.width}×${photo.height}` : ''}
                {sighting.lit === false ? ' · taken without the light, sleep mode was on' : ''}
              </span>
              <span className="vis-dots">
                {photos.map((one, index) => (
                  <button
                    aria-label={`Photograph ${index + 1}`}
                    className={index === shown ? 'is-on' : ''}
                    key={one.path}
                    onClick={() => setShown(index)}
                    type="button"
                  />
                ))}
              </span>
            </footer>
          </>
        )}

        <div className="vis-actions">
          <button className="vis-later" onClick={onLater} type="button">
            See later
          </button>
          <button className="vis-seen" onClick={onSeen} type="button">
            Seen
          </button>
        </div>
      </div>
    </div>
  )
}
