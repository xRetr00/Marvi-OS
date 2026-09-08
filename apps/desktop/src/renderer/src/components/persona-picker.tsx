/**
 * Which Marvi you are talking to.
 *
 * Her character used to be one shipped file with one position in it —
 * "Silence is the default and it is not failure. Most of what you notice is
 * not worth a word." That is a real stance, held on purpose, and it produces
 * an assistant that answers "hi" with "hi" and volunteers nothing for the rest
 * of the day. It is right for somebody who wants to be left alone and wrong
 * for somebody who wants a colleague, and there was no way to say which you
 * were.
 *
 * So it is a choice. The old text is still here, as *Marvi, quiet* — nothing
 * was thrown away, it just stopped being the only option.
 *
 * The chat window is not on this list on purpose. It differs because the
 * medium differs — you are reading rather than listening, so length is cheap
 * and a table beats a paragraph — and that is not a matter of taste. Whichever
 * one you pick here, chat gets its own.
 */
import { Check } from 'lucide-react'
import React, { useEffect, useState } from 'react'

interface Persona {
  name: string
  label: string
  blurb: string
}

export function PersonaPicker(): React.JSX.Element | null {
  const [offered, setOffered] = useState<Persona[]>([])
  const [chosen, setChosen] = useState('')
  const [saving, setSaving] = useState('')

  useEffect(() => {
    let alive = true
    void (async () => {
      const answer = await window.marvi?.getPersonas()
      if (!alive || !answer) return
      setOffered(answer.available ?? [])
      setChosen(answer.chosen ?? '')
    })()
    return () => {
      alive = false
    }
  }, [])

  const pick = async (name: string): Promise<void> => {
    if (name === chosen) return
    setSaving(name)
    const answer = await window.marvi?.choosePersona(name)
    if (answer) {
      setChosen(answer.chosen ?? name)
      setOffered(answer.available ?? offered)
    }
    setSaving('')
  }

  if (offered.length === 0) return null

  return (
    <section className="persona">
      <header>
        <h2>Who she is</h2>
        <p>How she talks and when she speaks first. It takes effect on the next turn.</p>
      </header>
      <div className="persona-list">
        {offered.map((one) => (
          <button
            aria-pressed={one.name === chosen}
            className={`persona-one${one.name === chosen ? ' is-on' : ''}`}
            disabled={saving !== ''}
            key={one.name}
            onClick={() => void pick(one.name)}
            type="button"
          >
            <span className="persona-tick">
              {one.name === chosen ? <Check aria-hidden="true" /> : null}
            </span>
            <span>
              <strong>{one.label}</strong>
              <em>{one.blurb}</em>
            </span>
          </button>
        ))}
      </div>
      <p className="persona-foot">
        The chat window has its own — longer answers, Markdown, code in code blocks — whichever you
        choose here.
      </p>
    </section>
  )
}
