import { describe, expect, it } from 'vitest'

import { toolActivity, toolSentence } from './tool-verbs'

/**
 * Every one of these is a real registered tool name, taken from the Gateway's
 * `ToolSpec` registrations rather than invented — a verb table that reads well
 * against names nobody uses is worth nothing.
 */
describe('toolSentence', () => {
  it('says what a reading tool is actually doing', () => {
    expect(toolSentence('marvi_logs', true)).toBe('Marvi is reading Marvi’s logs')
    expect(toolSentence('file_read', true)).toBe('Marvi is reading a file')
    expect(toolSentence('read_screen', true)).toBe('Marvi is looking at the screen')
  })

  it('keeps “using” for the tools where it is the honest word', () => {
    // Any narrower verb here would be a guess about which part of the machine
    // is being driven.
    expect(toolSentence('computer_action', true)).toBe('Marvi is using the computer')
    expect(toolSentence('browser_action', true)).toBe('Marvi is using the browser')
  })

  it('covers the other verbs the tools actually have', () => {
    expect(toolActivity('file_write', true)).toBe('writing a file')
    expect(toolActivity('file_edit', true)).toBe('patching a file')
    expect(toolActivity('file_search', true)).toBe('searching a file')
    expect(toolActivity('web_search', true)).toBe('searching the web')
    expect(toolActivity('browser_open', true)).toBe('surfing')
    expect(toolActivity('terminal_run', true)).toBe('running a command')
    expect(toolActivity('memory_recall', true)).toBe('recalling memory')
    expect(toolActivity('room_state', true)).toBe('checking the room')
    expect(toolActivity('skill_install', true)).toBe('installing a skill')
  })

  it('reads the verb whichever end of the name it is on', () => {
    // `file_read` is object-then-verb; `send_email` is verb-then-object.
    expect(toolActivity('file_read', true)).toBe('reading a file')
    expect(toolActivity('send_email', true)).toBe('sending an email')
  })

  it('does not mistake a leading noun for a verb', () => {
    // `memory_search` must not be read as the verb "memory".
    expect(toolActivity('memory_search', true)).toBe('searching memory')
  })

  it('switches to past tense once the call is finished', () => {
    expect(toolSentence('marvi_logs', false)).toBe('Marvi read Marvi’s logs')
    expect(toolSentence('file_write', false)).toBe('Marvi wrote a file')
    expect(toolSentence('web_search', false)).toBe('Marvi searched the web')
    expect(toolSentence('computer_action', false)).toBe('Marvi used the computer')
  })

  it('falls back to “using” for a tool it has never seen', () => {
    // MCP servers bring their own names. A confident wrong verb is worse than
    // a vague right one.
    expect(toolActivity('acme_widgetise', true)).toBe('using Acme widgetise')
    expect(toolActivity('acme_widgetise', false)).toBe('used Acme widgetise')
  })

  it('never produces an empty sentence', () => {
    for (const name of ['', '   ', '___', 'k']) {
      expect(toolSentence(name, true).length).toBeGreaterThan('Marvi is '.length)
    }
  })
})
