/**
 * How sure the listener has to be before it counts as her name — as a number,
 * next to the evidence for choosing one.
 *
 * This was three fixed choices: Sensitive 0.35, Balanced 0.5, Strict 0.7.
 * Which is fine until the thing you need is 0.52, and it gave no way to know
 * that you needed it. The recorded fires told the whole story and were shown
 * nowhere:
 *
 *     23:29:58   0.396
 *     22:40:59   0.477
 *     22:32:04   0.475
 *
 * Three in 58 minutes, every one a false alarm, every one above a threshold
 * of 0.35 and below the 0.5 default. Reading that column is how you pick the
 * number — set it above the highest false alarm you can see, and low enough
 * that your own voice still clears it.
 *
 * So: a number you can type, and the log beside it. Scores at or above the
 * current threshold are the ones that actually woke her, and are marked.
 */
import { useState } from 'react'
import { DataStream } from './ui/data-stream'
import { HIGHEST, LOWEST, asEntries, loudest, readable, usableThreshold } from './wake-confidence-utils'
import './wake-confidence.css'

export function WakeConfidence({
  threshold,
  recent,
  heardTotal,
  onChange
}: {
  threshold: number
  recent: { at: number; confidence: number }[]
  heardTotal: number
  onChange: (value: string) => void
}): React.JSX.Element {
  // Null means "not editing", so the field shows whatever is saved and
  // follows it when it changes elsewhere. Mirroring the prop into state with
  // an effect instead would overwrite half-typed input on the next poll --
  // and this panel polls.
  const [draft, setDraft] = useState<string | null>(null)
  const typed = draft ?? String(threshold)

  const parsed = usableThreshold(typed)
  const usable = parsed !== null
  const changed = parsed !== null && parsed !== threshold
  const highest = loudest(recent)

  const save = (): void => {
    if (parsed === null || parsed === threshold) return
    onChange(String(parsed))
    setDraft(null)
  }

  return (
    <div className="wake-confidence">
      <div className="wake-confidence-row">
        <label htmlFor="wake-threshold">Confidence needed</label>
        <input
          aria-describedby="wake-threshold-help"
          className={usable ? 'wake-threshold' : 'wake-threshold is-bad'}
          id="wake-threshold"
          max={HIGHEST}
          min={LOWEST}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') save()
          }}
          step={0.01}
          type="number"
          value={typed}
        />
        <button
          className="wake-threshold-save"
          disabled={!changed}
          onClick={save}
          type="button"
        >
          Save
        </button>
      </div>
      <p className="wake-confidence-help" id="wake-threshold-help">
        {usable
          ? `Between ${LOWEST} and ${HIGHEST}. Higher means she asks you to say it clearly; lower means more false alarms. Takes effect when the listener restarts.`
          : `That is not a number the listener will accept — it has to be between ${LOWEST} and ${HIGHEST}.`}
      </p>
      {highest > 0 ? (
        <p className="wake-confidence-help">
          The loudest false alarm you can see below scored {readable(highest)}. A threshold
          above that would have stopped it.
        </p>
      ) : null}
      <DataStream
        empty={
          heardTotal > 0
            ? 'Fired before this listener started; nothing recorded since.'
            : 'She has not woken since the listener started.'
        }
        entries={asEntries(recent, threshold)}
        maxVisible={6}
        streaming={false}
        title="Wake detections"
      />
    </div>
  )
}
