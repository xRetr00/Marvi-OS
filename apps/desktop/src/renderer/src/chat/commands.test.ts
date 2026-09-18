import { describe, expect, it } from 'vitest'

import { commandArgument, SLASH_COMMANDS, slashTrigger } from './commands'

describe('slash commands', () => {
  it('opens only on a slash that starts the draft', () => {
    expect(slashTrigger('/goal', '/', 5)).toEqual({ query: 'goal', offset: 0, endOffset: 5 })
    // A slash inside a sentence is a slash inside a sentence.
    expect(slashTrigger('and/or', '/', 6)).toBeNull()
    expect(slashTrigger('see D:/Marvi-OS', '/', 15)).toBeNull()
    expect(slashTrigger('', '/', 0)).toBeNull()
    expect(slashTrigger('/goal', '@', 5)).toBeNull()
  })

  it('keeps the popover open once the argument is being typed', () => {
    // The default detection stops at the first space, which would leave
    // `/goal buy milk` with no way to run it.
    const trigger = slashTrigger('/goal buy milk before six', '/', 25)
    expect(trigger).not.toBeNull()
    expect(trigger?.query).toBe('goal')
    // The whole draft is the replace bound, so running one clears the line.
    expect(trigger?.endOffset).toBe(25)
  })

  it('reads the rest of the line as the argument', () => {
    expect(commandArgument('/goal buy milk', 'goal')).toBe('buy milk')
    expect(commandArgument('  /goal   buy milk  ', 'goal')).toBe('buy milk')
    expect(commandArgument('/goal', 'goal')).toBe('')
    // Matched on its description rather than its name: the draft is not an
    // argument for this command, so it does not become one.
    expect(commandArgument('fold this please', 'compress')).toBe('')
  })

  it('offers only what typing English cannot already do', () => {
    expect(SLASH_COMMANDS.map((one) => one.id)).toEqual(['compress', 'goal', 'new'])
    for (const command of SLASH_COMMANDS) {
      expect(command.description.length).toBeGreaterThan(30)
    }
  })
})
