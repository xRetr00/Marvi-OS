/**
 * Choosing when a job runs, without knowing any syntax.
 *
 * The field was a text box next to the word "When", and the grammar it
 * accepted lived in the Gateway. Typing "every day at 18:00" -- the obvious
 * thing -- was rejected, and so was every example the form itself offered.
 * The parser now reads those phrases, and this makes it so nobody has to
 * discover them: pick a rhythm, pick a time, and the phrase is written for
 * you.
 *
 * It still writes into the same text field rather than replacing it, because
 * a cron expression is a legitimate thing to want and taking the box away
 * would be a downgrade for anybody who knows what they are doing.
 */
import React, { useEffect, useState } from 'react'

type Rhythm = 'once' | 'daily' | 'weekdays' | 'weekly' | 'interval'

const RHYTHMS: { id: Rhythm; label: string }[] = [
  { id: 'daily', label: 'Every day' },
  { id: 'weekdays', label: 'Weekdays' },
  { id: 'weekly', label: 'One day a week' },
  { id: 'interval', label: 'On a timer' },
  { id: 'once', label: 'Once' }
]

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

/** Intervals worth offering. Below the Gateway's floor is not one of them. */
const EVERY = [
  { minutes: 15, label: '15 minutes' },
  { minutes: 30, label: '30 minutes' },
  { minutes: 60, label: 'hour' },
  { minutes: 180, label: '3 hours' },
  { minutes: 360, label: '6 hours' },
  { minutes: 720, label: '12 hours' }
]

/** The phrase the Gateway parses, built from the choices. */
function phraseFor(rhythm: Rhythm, time: string, day: string, minutes: number): string {
  if (rhythm === 'interval') return `every ${minutes} minutes`
  if (rhythm === 'once') return `tomorrow at ${time}`
  if (rhythm === 'weekdays') return `every weekday at ${time}`
  if (rhythm === 'weekly') return `every ${day} at ${time}`
  return `every day at ${time}`
}

export function WhenPicker({
  value,
  onChange
}: {
  value: string
  onChange: (next: string) => void
}): React.JSX.Element {
  const [rhythm, setRhythm] = useState<Rhythm>('daily')
  const [time, setTime] = useState('09:00')
  const [day, setDay] = useState('monday')
  const [minutes, setMinutes] = useState(30)
  const [typing, setTyping] = useState(false)

  // The picker owns the field while it is being used, and lets go the moment
  // somebody types something of their own -- a cron expression, usually.
  useEffect(() => {
    if (typing) return
    onChange(phraseFor(rhythm, time, day, minutes))
    // `onChange` is a new closure every render in most callers; depending on
    // it would rewrite the field on every keystroke elsewhere in the form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rhythm, time, day, minutes, typing])

  return (
    <div className="when-picker">
      <div className="when-rhythms">
        {RHYTHMS.map((one) => (
          <button
            aria-pressed={!typing && rhythm === one.id}
            className={!typing && rhythm === one.id ? 'is-on' : ''}
            key={one.id}
            onClick={() => {
              setTyping(false)
              setRhythm(one.id)
            }}
            type="button"
          >
            {one.label}
          </button>
        ))}
      </div>

      <div className="when-detail">
        {rhythm === 'interval' ? (
          <label>
            <span>Every</span>
            <select
              onChange={(event) => {
                setTyping(false)
                setMinutes(Number(event.target.value))
              }}
              value={minutes}
            >
              {EVERY.map((one) => (
                <option key={one.minutes} value={one.minutes}>
                  {one.label}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <>
            {rhythm === 'weekly' && (
              <label>
                <span>On</span>
                <select
                  onChange={(event) => {
                    setTyping(false)
                    setDay(event.target.value)
                  }}
                  value={day}
                >
                  {DAYS.map((one) => (
                    <option key={one} value={one}>
                      {one[0].toUpperCase() + one.slice(1)}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              <span>At</span>
              {/* A real time input: it respects the machine's 12/24-hour
                  setting and cannot produce 25:00, which the text box could. */}
              <input
                onChange={(event) => {
                  setTyping(false)
                  setTime(event.target.value || '09:00')
                }}
                type="time"
                value={time}
              />
            </label>
          </>
        )}
      </div>

      <label className="when-exact">
        <span>Or write it yourself</span>
        <input
          onChange={(event) => {
            setTyping(true)
            onChange(event.target.value)
          }}
          placeholder="0 6 * * 1-5"
          type="text"
          value={value}
        />
      </label>
    </div>
  )
}
