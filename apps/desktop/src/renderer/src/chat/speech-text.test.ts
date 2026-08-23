import { describe, expect, it } from 'vitest'

import { markdownToSpeechChunks } from './speech-text'

describe('markdownToSpeechChunks', () => {
  it('speaks visible prose and omits formatting, code, and URL destinations', () => {
    const speech = markdownToSpeechChunks(
      '# Result\n\nRead **this** [guide](https://example.com/private).\n\n```ts\nSECRET()\n```'
    ).join(' ')

    expect(speech).toContain('Result')
    expect(speech).toContain('Read this guide')
    expect(speech).toContain('Code block omitted.')
    expect(speech).not.toContain('SECRET')
    expect(speech).not.toContain('example.com')
  })

  it('turns tables and task lists into useful spoken structure', () => {
    const speech = markdownToSpeechChunks(
      '| Model | State |\n| --- | --- |\n| Local | Ready |\n\n- [x] Installed\n- [ ] Tested'
    ).join(' ')

    expect(speech).toContain('Table columns: Model, State.')
    expect(speech).toContain('Model: Local; State: Ready')
    expect(speech).toContain('Completed: Installed')
    expect(speech).toContain('Not completed: Tested')
  })
})
