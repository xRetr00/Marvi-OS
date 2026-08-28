import { describe, expect, it } from 'vitest'

import {
  getRequiredFieldsForConnector,
  validateRequiredFieldValues
} from './connectorRequiredFields'

describe('connector required-field registry', () => {
  it('has no required fields for a connector with no registry entry', () => {
    expect(getRequiredFieldsForConnector('gmail')).toEqual([])
  })

  it('returns the Jira subdomain field', () => {
    const fields = getRequiredFieldsForConnector('jira')
    expect(fields).toHaveLength(1)
    expect(fields[0].key).toBe('subdomain')
    expect(fields[0].suffix).toBe('.atlassian.net')
  })

  it('rejects an empty required value', () => {
    const fields = getRequiredFieldsForConnector('jira')
    const errors = validateRequiredFieldValues(fields, {})
    expect(errors.subdomain).toBeTruthy()
  })

  it('rejects a full URL where only a subdomain label is expected', () => {
    const fields = getRequiredFieldsForConnector('jira')
    const errors = validateRequiredFieldValues(fields, {
      subdomain: 'https://your-team.atlassian.net'
    })
    expect(errors.subdomain).toBeTruthy()
  })

  it('accepts a valid subdomain label', () => {
    const fields = getRequiredFieldsForConnector('jira')
    const errors = validateRequiredFieldValues(fields, { subdomain: 'your-team' })
    expect(errors).toEqual({})
  })

  it('passes validation trivially when the connector has no required fields', () => {
    expect(validateRequiredFieldValues([], {})).toEqual({})
  })
})
