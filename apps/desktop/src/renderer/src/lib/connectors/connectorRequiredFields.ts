/**
 * Per-connector declarative registry for provider-specific fields the connect
 * flow must collect before calling `connectConnector`. Without these, some
 * backends refuse the OAuth handoff with a "missing required fields" error
 * that otherwise reads as an opaque failure.
 *
 * Adding a new provider-specific field is a single registry entry — no
 * per-connector branches inside `ConnectorConnectModal` or the connect hook.
 * Mirrors the shape (not the code) of openhuman's `toolkitRequiredFields.ts`.
 *
 * Field values are forwarded verbatim as extra connect parameters; each
 * entry's `key` is also the parameter name the backend expects.
 */
export interface ConnectorRequiredField {
  /** Field id, and the parameter name forwarded to `connectConnector`. */
  key: string
  label: string
  hint?: string
  placeholder?: string
  /** Fixed suffix rendered inside the input (e.g. `.atlassian.net`). Cosmetic only. */
  suffix?: string
  /** Return null when valid, or an error string when invalid. Omitted means only "not empty" is enforced. */
  validate?: (value: string) => string | null
}

function validateSubdomainLabel(value: string): string | null {
  const trimmed = value.trim()
  if (!/^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$|^[a-z0-9]$/i.test(trimmed)) {
    return 'Enter just the subdomain, not the full URL.'
  }
  return null
}

export const CONNECTOR_REQUIRED_FIELDS: Readonly<
  Record<string, readonly ConnectorRequiredField[]>
> = Object.freeze({
  whatsapp: [
    {
      key: 'waba_id',
      label: 'WhatsApp Business Account ID',
      hint: 'Found in Meta Business Manager under WhatsApp Accounts.',
      placeholder: '1234567890'
    }
  ],
  jira: [
    {
      key: 'subdomain',
      label: 'Atlassian subdomain',
      hint: 'The part before .atlassian.net in your site URL.',
      placeholder: 'your-team',
      suffix: '.atlassian.net',
      validate: validateSubdomainLabel
    }
  ],
  dynamics365: [
    {
      key: 'org_name',
      label: 'Organization name',
      hint: 'The part before .crm.dynamics.com in your org URL.',
      placeholder: 'your-org',
      suffix: '.crm.dynamics.com',
      validate: validateSubdomainLabel
    }
  ]
})

/** The required-field list for a connector slug (empty when none). */
export function getRequiredFieldsForConnector(slug: string): readonly ConnectorRequiredField[] {
  return CONNECTOR_REQUIRED_FIELDS[slug] ?? []
}

/** Validate a values map against a connector's required fields. Empty result means all valid. */
export function validateRequiredFieldValues(
  fields: readonly ConnectorRequiredField[],
  values: Record<string, string>
): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const field of fields) {
    const value = (values[field.key] ?? '').trim()
    if (!value) {
      errors[field.key] = 'This field is required.'
      continue
    }
    const customError = field.validate?.(value)
    if (customError) errors[field.key] = customError
  }
  return errors
}
