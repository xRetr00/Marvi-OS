export interface Session {
  id: string
  title: string
  updatedAt: string
  messageCount: number
}

/**
 * Session list sidebar. Today Marvi Gateway keeps a single transcript, so the
 * list holds one active session; the component is data-driven so it scales to
 * multiple sessions without changing once the backend grows them.
 */
export function Sessions({
  sessions,
  activeId,
  onSelect,
  onNew
}: {
  sessions: Session[]
  activeId: string
  onSelect: (id: string) => void
  onNew: () => void
}): React.JSX.Element {
  return (
    <aside className="chat-sessions" aria-label="Chat sessions">
      <div className="chat-sessions-head">
        <span>SESSIONS</span>
        <button className="chat-new" type="button" onClick={onNew}>
          + NEW
        </button>
      </div>
      {sessions.length === 0 ? (
        <span className="chat-sessions-empty">NO SESSIONS YET</span>
      ) : (
        <ul className="chat-session-list">
          {sessions.map((session) => (
            <li key={session.id}>
              <button
                className={session.id === activeId ? 'chat-session active' : 'chat-session'}
                type="button"
                onClick={() => onSelect(session.id)}
              >
                <span className="chat-session-title">{session.title}</span>
                <span className="chat-session-meta">
                  {session.messageCount} msgs
                  {session.updatedAt ? ` · ${session.updatedAt}` : ''}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
