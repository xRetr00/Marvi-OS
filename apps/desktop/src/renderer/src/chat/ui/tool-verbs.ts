/**
 * What Marvi is doing, said in the verb that fits the tool.
 *
 * "Marvi is using web search" is technically true and tells you nothing you
 * could not see. "Marvi is searching the web" is the same length and is the
 * actual sentence. The distinction matters most on the tools that read: a
 * status line that says *using* while Marvi is halfway through your log file
 * makes every tool look like the same opaque machine.
 *
 * `using` is still right for the tools where it is the honest word -- the
 * computer, the browser -- because "Marvi is using the computer" is exactly
 * what is happening and any narrower verb would be a guess about which part.
 *
 * ## Why a rule and not a list
 *
 * Marvi's tools are named `object_verb` (`file_read`, `memory_search`) or
 * `verb_object` (`read_screen`, `send_email`), so the verb is usually already
 * in the name. Reading it out means a tool added next week gets a sentence
 * without anyone editing this file -- which matters because MCP servers bring
 * their own names and nobody here will ever see that list. The overrides below
 * are only for the handful the rule gets wrong or has nothing to work with.
 */

/** Present participle and past tense, for "Marvi is X" and "Marvi X". */
type Tense = readonly [present: string, past: string]

/** Verb tokens as they appear inside tool names. */
const VERBS: Record<string, Tense> = {
  action: ['using', 'used'],
  add: ['adding to', 'added to'],
  control: ['using', 'used'],
  delete: ['deleting from', 'deleted from'],
  edit: ['patching', 'patched'],
  execute: ['running', 'ran'],
  extract: ['reading', 'read'],
  fetch: ['reading', 'read'],
  find: ['searching', 'searched'],
  forget: ['forgetting', 'forgot'],
  health: ['checking', 'checked'],
  install: ['installing', 'installed'],
  link: ['connecting', 'connected'],
  list: ['checking', 'checked'],
  logs: ['reading', 'read'],
  move: ['rescheduling', 'rescheduled'],
  neighbours: ['recalling', 'recalled'],
  now: ['checking', 'checked'],
  open: ['surfing', 'surfed'],
  presence: ['checking', 'checked'],
  read: ['reading', 'read'],
  recall: ['recalling', 'recalled'],
  reflect: ['reflecting on', 'reflected on'],
  refresh: ['refreshing', 'refreshed'],
  remember: ['saving to', 'saved to'],
  remove: ['removing from', 'removed from'],
  run: ['running', 'ran'],
  save: ['saving', 'saved'],
  search: ['searching', 'searched'],
  send: ['sending', 'sent'],
  set: ['adjusting', 'adjusted'],
  state: ['checking', 'checked'],
  status: ['checking', 'checked'],
  stop: ['stopping', 'stopped'],
  today: ['checking', 'checked'],
  tools: ['using', 'used'],
  unlink: ['disconnecting', 'disconnected'],
  write: ['writing', 'wrote']
}

/** How the thing being acted on is said, when the bare token reads oddly. */
const SUBJECTS: Record<string, string> = {
  account: 'an account',
  activity: 'today’s activity',
  browser: 'the browser',
  calendar: 'the calendar',
  computer: 'the computer',
  file: 'a file',
  marvi: 'Marvi’s logs',
  memory: 'memory',
  process: 'a process',
  room: 'the room',
  schedule: 'the schedule',
  screen: 'the screen',
  skill: 'a skill',
  terminal: 'the terminal',
  web: 'the web'
}

/**
 * The tools the rule cannot read: no verb in the name, or a verb that would
 * produce the wrong sentence.
 */
const OVERRIDES: Record<string, readonly [present: string, past: string]> = {
  ask_on_screen: ['asking you something', 'asked you something'],
  ask_secret: ['asking you for a credential', 'asked you for a credential'],
  browser_action: ['using the browser', 'used the browser'],
  browser_control: ['using the browser', 'used the browser'],
  browser_open: ['surfing', 'surfed'],
  browser_read_image: ['looking at the page', 'looked at the page'],
  clarify: ['asking you something', 'asked you something'],
  claude: ['delegating to Claude', 'delegated to Claude'],
  codex: ['delegating to Codex', 'delegated to Codex'],
  computer_action: ['using the computer', 'used the computer'],
  computer_control: ['using the computer', 'used the computer'],
  cronjob: ['scheduling a job', 'scheduled a job'],
  delegate_to_coder: ['delegating to a coder', 'delegated to a coder'],
  delegated_status: ['checking on the coder', 'checked on the coder'],
  marvi_logs: ['reading Marvi’s logs', 'read Marvi’s logs'],
  memory_reflect: ['reflecting on memory', 'reflected on memory'],
  note_about_user: ['making a note about you', 'made a note about you'],
  read_screen: ['looking at the screen', 'looked at the screen'],
  send_email: ['sending an email', 'sent an email'],
  terminal_run: ['running a command', 'ran a command'],
  web_search: ['searching the web', 'searched the web']
}

/** `file_read` -> `['file', 'read']`. */
function tokens(name: string): string[] {
  return name
    .split(/[^a-z0-9]+/i)
    .filter(Boolean)
    .map((token) => token.toLowerCase())
}

/** Title-case only the first word, so a name reads as prose not as a label. */
function humanise(words: string[]): string {
  const text = words.join(' ')
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : ''
}

/**
 * The phrase after "Marvi is" / "Marvi ", for one tool.
 *
 * Falls all the way back to "using <name>" rather than inventing a verb: an
 * MCP server's tool could be doing anything, and a confident wrong verb is
 * worse than a vague right one.
 */
export function toolActivity(toolName: string, running: boolean): string {
  const override = OVERRIDES[toolName]
  if (override) return override[running ? 0 : 1]

  const parts = tokens(toolName)
  if (!parts.length) return running ? 'using a tool' : 'used a tool'

  // Verb last (`file_read`) is the common shape here; verb first (`read_screen`)
  // is the other one. Checking last first keeps `memory_search` from being read
  // as the noun "memory".
  const lastIsVerb = VERBS[parts[parts.length - 1]]
  const firstIsVerb = VERBS[parts[0]]
  const [tense, rest] = lastIsVerb
    ? [lastIsVerb, parts.slice(0, -1)]
    : firstIsVerb
      ? [firstIsVerb, parts.slice(1)]
      : [null, parts]

  if (!tense) {
    return `${running ? 'using' : 'used'} ${humanise(parts)}`
  }

  const verb = tense[running ? 0 : 1]
  if (!rest.length) return verb
  const subject = SUBJECTS[rest[0]] ?? humanise(rest)
  return `${verb} ${subject}`
}

/** The whole line: "Marvi is reading a file", "Marvi searched the web". */
export function toolSentence(toolName: string, running: boolean): string {
  return `${running ? 'Marvi is' : 'Marvi'} ${toolActivity(toolName, running)}`
}
