/**
 * Local display metadata for connectors shown in the Capabilities grid.
 *
 * The Gateway's `/connectors` route answers *availability* (what is actually
 * reachable right now), never *identity* (names, categories, what the badge
 * says). Skills once fetched both from the network on first paint and the
 * page reported "Loading" for as long as the Gateway took to answer — on a
 * cold start, forever. This catalog ships with the renderer bundle so the
 * grid paints in the same frame as the page, and live status from the
 * Gateway only ever overlays it afterward. See `ConnectorsPanel`.
 *
 * Slugs are the Gateway/Composio toolkit slug and double as the join key
 * against `ConnectorRow.slug` from `GET /connectors`.
 */
export type ConnectorCategory = 'chat' | 'productivity' | 'tools' | 'social' | 'platform'

export interface ConnectorMeta {
  slug: string
  name: string
  category: ConnectorCategory
  description: string
  /** Short phrase for what authorizing this connector grants Marvi. */
  permissionLabel: string
}

export const CONNECTOR_CATEGORY_LABELS: Record<ConnectorCategory, string> = {
  chat: 'Chat',
  productivity: 'Productivity',
  tools: 'Tools & Automation',
  social: 'Social',
  platform: 'Platform'
}

export const CONNECTOR_CATALOG: readonly ConnectorMeta[] = Object.freeze([
  {
    slug: 'gmail',
    name: 'Gmail',
    category: 'chat',
    description: 'Read, search, and send email on your behalf.',
    permissionLabel: 'Read and send email'
  },
  {
    slug: 'slack',
    name: 'Slack',
    category: 'chat',
    description: 'Post and read messages in your workspace.',
    permissionLabel: 'Read and post messages'
  },
  {
    slug: 'discord',
    name: 'Discord',
    category: 'chat',
    description: 'Read and post messages in servers you belong to.',
    permissionLabel: 'Read and post messages'
  },
  {
    slug: 'microsoft_teams',
    name: 'Microsoft Teams',
    category: 'chat',
    description: 'Read and post messages in Teams channels.',
    permissionLabel: 'Read and post messages'
  },
  {
    slug: 'whatsapp',
    name: 'WhatsApp Business',
    category: 'chat',
    description: 'Send and receive WhatsApp Business messages.',
    permissionLabel: 'Send and receive messages'
  },
  {
    slug: 'googlecalendar',
    name: 'Google Calendar',
    category: 'productivity',
    description: 'Read your schedule and create or move events.',
    permissionLabel: 'Read and manage events'
  },
  {
    slug: 'googledrive',
    name: 'Google Drive',
    category: 'productivity',
    description: 'Find and read files stored in Drive.',
    permissionLabel: 'Read files'
  },
  {
    slug: 'googledocs',
    name: 'Google Docs',
    category: 'productivity',
    description: 'Read and edit documents.',
    permissionLabel: 'Read and edit documents'
  },
  {
    slug: 'googlesheets',
    name: 'Google Sheets',
    category: 'productivity',
    description: 'Read and edit spreadsheets.',
    permissionLabel: 'Read and edit spreadsheets'
  },
  {
    slug: 'notion',
    name: 'Notion',
    category: 'productivity',
    description: 'Read and write pages and databases.',
    permissionLabel: 'Read and write pages'
  },
  {
    slug: 'todoist',
    name: 'Todoist',
    category: 'productivity',
    description: 'Read and manage your task lists.',
    permissionLabel: 'Read and manage tasks'
  },
  {
    slug: 'trello',
    name: 'Trello',
    category: 'productivity',
    description: 'Read and manage boards and cards.',
    permissionLabel: 'Read and manage boards'
  },
  {
    slug: 'clickup',
    name: 'ClickUp',
    category: 'productivity',
    description: 'Read and manage tasks and spaces.',
    permissionLabel: 'Read and manage tasks'
  },
  {
    slug: 'linear',
    name: 'Linear',
    category: 'productivity',
    description: 'Read and manage issues and projects.',
    permissionLabel: 'Read and manage issues'
  },
  {
    slug: 'jira',
    name: 'Jira',
    category: 'tools',
    description: 'Read and manage issues in your Atlassian site.',
    permissionLabel: 'Read and manage issues'
  },
  {
    slug: 'github',
    name: 'GitHub',
    category: 'tools',
    description: 'Read repositories and manage issues and pull requests.',
    permissionLabel: 'Read and manage repositories'
  },
  {
    slug: 'gitlab',
    name: 'GitLab',
    category: 'tools',
    description: 'Read repositories and manage issues and merge requests.',
    permissionLabel: 'Read and manage repositories'
  },
  {
    slug: 'dynamics365',
    name: 'Dynamics 365',
    category: 'tools',
    description: 'Read and manage records in your Dynamics org.',
    permissionLabel: 'Read and manage records'
  },
  {
    slug: 'sentry',
    name: 'Sentry',
    category: 'tools',
    description: 'Read error reports and issue state.',
    permissionLabel: 'Read issues'
  },
  {
    slug: 'stripe',
    name: 'Stripe',
    category: 'tools',
    description: 'Read payments, customers, and invoices.',
    permissionLabel: 'Read billing data'
  },
  {
    slug: 'supabase',
    name: 'Supabase',
    category: 'tools',
    description: 'Read project data and manage tables.',
    permissionLabel: 'Read and manage project data'
  },
  {
    slug: 'twitter',
    name: 'X (Twitter)',
    category: 'social',
    description: 'Read and post to your timeline.',
    permissionLabel: 'Read and post updates'
  },
  {
    slug: 'linkedin',
    name: 'LinkedIn',
    category: 'social',
    description: 'Read your profile and post updates.',
    permissionLabel: 'Read and post updates'
  },
  {
    slug: 'instagram',
    name: 'Instagram',
    category: 'social',
    description: 'Read posts and account activity.',
    permissionLabel: 'Read account activity'
  },
  {
    slug: 'reddit',
    name: 'Reddit',
    category: 'social',
    description: 'Read posts and comments across your subscriptions.',
    permissionLabel: 'Read posts and comments'
  },
  {
    slug: 'facebook',
    name: 'Facebook',
    category: 'social',
    description: 'Read and post to pages you manage.',
    permissionLabel: 'Read and post updates'
  },
  {
    slug: 'salesforce',
    name: 'Salesforce',
    category: 'platform',
    description: 'Read and manage CRM records.',
    permissionLabel: 'Read and manage records'
  },
  {
    slug: 'hubspot',
    name: 'HubSpot',
    category: 'platform',
    description: 'Read and manage contacts and deals.',
    permissionLabel: 'Read and manage records'
  },
  {
    slug: 'onedrive',
    name: 'OneDrive',
    category: 'platform',
    description: 'Find and read files stored in OneDrive.',
    permissionLabel: 'Read files'
  },
  {
    slug: 'dropbox',
    name: 'Dropbox',
    category: 'platform',
    description: 'Find and read files stored in Dropbox.',
    permissionLabel: 'Read files'
  },
  {
    slug: 'box',
    name: 'Box',
    category: 'platform',
    description: 'Find and read files stored in Box.',
    permissionLabel: 'Read files'
  }
])

const CATALOG_BY_SLUG = new Map(CONNECTOR_CATALOG.map((entry) => [entry.slug, entry]))

export function connectorMeta(slug: string): ConnectorMeta | undefined {
  return CATALOG_BY_SLUG.get(slug)
}

/** Two-letter monogram for the card badge when no richer glyph is warranted. */
export function connectorMonogram(name: string): string {
  const trimmed = name.trim()
  if (!trimmed) return '??'
  const words = trimmed.split(/\s+/)
  if (words.length === 1) return trimmed.slice(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}
