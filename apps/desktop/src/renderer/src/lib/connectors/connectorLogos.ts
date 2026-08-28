/**
 * Real brand marks for the connector grid.
 *
 * The renderer's CSP is `img-src 'self' data:`, so a logo CDN is blocked
 * outright — and loosening it to reach one would put a remote host in the
 * content policy of an app whose whole premise is that it runs locally. These
 * are inline SVG components instead: markup, not images, so the policy does
 * not apply and nothing is fetched at runtime or fails offline.
 *
 * Imported one icon at a time rather than from the package index. The barrel
 * is 405 KB of 6,511 icons; `@thesvg/react/gmail` is about 2 KB, and thirty-one
 * of those is a rounding error next to pulling in every brand that exists.
 *
 * A slug missing from here is not an error — `ConnectorCard` falls back to the
 * tinted monogram, which is also what a connector added to the catalog before
 * anyone finds its mark will show.
 */
import type { ComponentType, SVGProps } from 'react'

import Box from '@thesvg/react/box'
import Clickup from '@thesvg/react/clickup'
import Discord from '@thesvg/react/discord'
import Dropbox from '@thesvg/react/dropbox'
import Dynamics365 from '@thesvg/react/microsoft-dynamics-365'
import Facebook from '@thesvg/react/facebook'
import Github from '@thesvg/react/github'
import Gitlab from '@thesvg/react/gitlab'
import Gmail from '@thesvg/react/gmail'
import GoogleCalendar from '@thesvg/react/google-calendar'
import GoogleDocs from '@thesvg/react/google-docs'
import GoogleDrive from '@thesvg/react/google-drive'
import GoogleSheets from '@thesvg/react/google-sheets'
import Hubspot from '@thesvg/react/hubspot'
import Instagram from '@thesvg/react/instagram'
import Jira from '@thesvg/react/jira'
import Linear from '@thesvg/react/linear'
import Linkedin from '@thesvg/react/linkedin'
import Notion from '@thesvg/react/notion'
import OneDrive from '@thesvg/react/microsoft-onedrive'
import Reddit from '@thesvg/react/reddit'
import Salesforce from '@thesvg/react/salesforce'
import Sentry from '@thesvg/react/sentry'
import Slack from '@thesvg/react/slack'
import Stripe from '@thesvg/react/stripe'
import Supabase from '@thesvg/react/supabase'
import Teams from '@thesvg/react/microsoft-teams'
import Todoist from '@thesvg/react/todoist'
import Trello from '@thesvg/react/trello'
import Whatsapp from '@thesvg/react/whatsapp'
import X from '@thesvg/react/x-formerly-twitter'
import Youtube from '@thesvg/react/youtube'

export type ConnectorLogo = ComponentType<SVGProps<SVGSVGElement>>

/** Keyed by the same toolkit slug the catalog and `GET /connectors` use. */
export const CONNECTOR_LOGOS: Readonly<Record<string, ConnectorLogo>> = Object.freeze({
  box: Box,
  clickup: Clickup,
  discord: Discord,
  dropbox: Dropbox,
  dynamics365: Dynamics365,
  facebook: Facebook,
  github: Github,
  gitlab: Gitlab,
  gmail: Gmail,
  googlecalendar: GoogleCalendar,
  googledocs: GoogleDocs,
  googledrive: GoogleDrive,
  googlesheets: GoogleSheets,
  hubspot: Hubspot,
  instagram: Instagram,
  jira: Jira,
  linear: Linear,
  linkedin: Linkedin,
  notion: Notion,
  one_drive: OneDrive,
  reddit: Reddit,
  salesforce: Salesforce,
  sentry: Sentry,
  slack: Slack,
  stripe: Stripe,
  supabase: Supabase,
  microsoft_teams: Teams,
  todoist: Todoist,
  trello: Trello,
  whatsapp: Whatsapp,
  twitter: X,
  youtube: Youtube
})
