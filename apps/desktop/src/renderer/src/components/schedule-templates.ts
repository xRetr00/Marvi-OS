import type { NewSchedule, ScheduleRow } from '../../../shared/runtime'

export interface ScheduleTemplate {
  id: string
  label: string
  description: string
  schedule: NewSchedule
}

/** Useful starting points, intentionally local and editable before creation. */
export const SCHEDULE_TEMPLATES: ScheduleTemplate[] = [
  {
    id: 'morning-briefing',
    label: 'Morning briefing',
    description: 'Weekday priorities from the information Marvi can reach.',
    schedule: {
      name: 'Morning briefing',
      when: 'every weekday at 08:00',
      mode: 'agent',
      prompt:
        'Review my calendar, recent messages, and open commitments. Give me a short morning briefing ordered by urgency.',
      delivery: 'local'
    }
  },
  {
    id: 'stand-up-reminder',
    label: 'Stand-up reminder',
    description: 'A spoken reminder ten minutes before the workday stand-up.',
    schedule: {
      name: 'Stand-up in ten minutes',
      when: 'every weekday at 09:50',
      mode: 'action',
      action: 'remind',
      message: 'Stand-up starts in ten minutes.'
    }
  },
  {
    id: 'weekly-review',
    label: 'Weekly review',
    description: 'A concise Friday summary of progress and loose ends.',
    schedule: {
      name: 'Weekly review',
      when: 'every friday at 17:00',
      mode: 'agent',
      prompt:
        'Summarize this week’s completed work, unresolved commitments, and the three most important next steps. Keep it concise.',
      delivery: 'local'
    }
  },
  {
    id: 'quiet-reflection',
    label: 'Nightly reflection',
    description: 'Runs Marvi’s fixed reflection action without speaking.',
    schedule: {
      name: 'Nightly reflection',
      when: 'every day at 23:00',
      mode: 'action',
      action: 'reflect',
      message: ''
    }
  }
]

/** Convert the stored schedule shape back into input accepted by the parser. */
export function editableWhen(row: ScheduleRow): string {
  if (row.kind === 'interval') return `every ${row.expression} minutes`
  return row.expression
}
