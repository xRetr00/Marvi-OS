import React, { useState } from 'react'
import { Trash2, X } from 'lucide-react'

import type { MemoryEntry, MemoryGraphNode } from '../../../shared/runtime'

/**
 * The node you clicked, and what you can do about it.
 *
 * The graph was read-only, which made it a picture rather than a tool: a wrong
 * relation is obvious on a canvas long before it is obvious anywhere else --
 * "Marvi is based on openhuman" sat there being visibly false -- and the only
 * way to correct one was to ask Marvi to do it in conversation.
 *
 * Two kinds of node, two kinds of edit. A **memory** has a subject and a body,
 * and is corrected in place so it keeps the id that any conclusion drawn from
 * it points at. An **entity** has a name, and correcting it is usually a merge:
 * the dreamer names things from whatever the memories called them, so one
 * person arrives twice as `Shreef` and `Shereef` with half the edges each.
 *
 * Mounted with the node's id as its key, so opening a different node builds a
 * fresh panel rather than resetting six pieces of state in an effect. The
 * fields are drafts; remounting is what discards an unsaved one.
 */
export function GraphNodePanel({
  node,
  entries,
  onClose,
  onChanged
}: {
  node: MemoryGraphNode
  /** The memory rows already on the page, so opening a node costs no request. */
  entries: MemoryEntry[]
  onClose: () => void
  onChanged: () => void
}): React.JSX.Element {
  const memoryId = node.id.startsWith('memory:') ? Number(node.id.slice(7)) : 0
  const entry = entries.find((row) => row.id === memoryId)
  const isEntity = node.id.startsWith('entity:')

  const [subject, setSubject] = useState(entry?.subject ?? node.label)
  const [body, setBody] = useState(entry?.body ?? '')
  const [name, setName] = useState(node.label)
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('')
  const [armed, setArmed] = useState(false)

  const run = async (what: string, work: () => Promise<unknown>): Promise<void> => {
    setBusy(what)
    try {
      const result = (await work()) as { detail?: string } | null
      // A refusal says why. The store can decline an edit -- a credential in
      // the new text, an id that no longer exists -- and showing nothing would
      // read as the button not working.
      setNotice(typeof result?.detail === 'string' ? result.detail : '')
      onChanged()
    } finally {
      setBusy('')
    }
  }

  return (
    <aside className="graph-node-panel">
      <header>
        <strong>{node.label}</strong>
        <button aria-label="Close" onClick={onClose} type="button">
          <X aria-hidden="true" />
        </button>
      </header>

      <dl>
        <div>
          <dt>Kind</dt>
          <dd>{node.kind}</dd>
        </div>
        {entry ? (
          <>
            <div>
              <dt>Source</dt>
              <dd>{entry.source.replace('import:', '') || 'marvi'}</dd>
            </div>
            <div>
              <dt>Stored</dt>
              <dd>{entry.at.slice(0, 10)}</dd>
            </div>
            <div>
              <dt>Trusted</dt>
              <dd>{entry.trusted ? 'yes' : 'came from outside'}</dd>
            </div>
          </>
        ) : null}
        {node.provenance && !entry ? (
          <div>
            <dt>Source</dt>
            <dd>{node.provenance}</dd>
          </div>
        ) : null}
      </dl>

      {entry ? (
        <>
          <label className="graph-node-field">
            <span>Subject</span>
            <input value={subject} onChange={(event) => setSubject(event.target.value)} />
          </label>
          <label className="graph-node-field">
            <span>What it says</span>
            <textarea
              rows={5}
              value={body}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          <div className="provider-actions">
            <button
              className="phase active"
              disabled={!!busy}
              onClick={() =>
                void run('save', () => window.marvi!.reviseMemory(memoryId, subject, body))
              }
              type="button"
            >
              {busy === 'save' ? 'Saving' : 'Save'}
            </button>
            {armed ? (
              <>
                <button
                  className="phase danger"
                  disabled={!!busy}
                  onClick={() =>
                    void run('delete', () => window.marvi!.deleteMemory(memoryId)).then(onClose)
                  }
                  type="button"
                >
                  <Trash2 aria-hidden="true" /> Delete it
                </button>
                <button className="phase" onClick={() => setArmed(false)} type="button">
                  Cancel
                </button>
              </>
            ) : (
              <button className="phase" onClick={() => setArmed(true)} type="button">
                Forget this
              </button>
            )}
          </div>
        </>
      ) : isEntity ? (
        <>
          <label className="graph-node-field">
            <span>Name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <p className="notice">
            Renaming to a name that already exists merges the two, keeping every relationship
            both had. That is usually what you want: the same person arriving twice under two
            spellings is the common way this graph goes wrong.
          </p>
          <div className="provider-actions">
            <button
              className="phase active"
              disabled={!!busy || name === node.label}
              onClick={() => void run('save', () => window.marvi!.editEntity(node.label, name, false))}
              type="button"
            >
              {busy === 'save' ? 'Saving' : 'Rename'}
            </button>
            {armed ? (
              <>
                <button
                  className="phase danger"
                  disabled={!!busy}
                  onClick={() =>
                    void run('delete', () =>
                      window.marvi!.editEntity(node.label, '', true)
                    ).then(onClose)
                  }
                  type="button"
                >
                  <Trash2 aria-hidden="true" /> Remove it
                </button>
                <button className="phase" onClick={() => setArmed(false)} type="button">
                  Cancel
                </button>
              </>
            ) : (
              <button className="phase" onClick={() => setArmed(true)} type="button">
                Remove from the graph
              </button>
            )}
          </div>
        </>
      ) : (
        <p className="notice">
          This is a grouping rather than something Marvi remembers, so there is nothing here to
          edit. Open one of the nodes under it.
        </p>
      )}

      {notice ? <p className="notice notice-warn">{notice}</p> : null}
    </aside>
  )
}
