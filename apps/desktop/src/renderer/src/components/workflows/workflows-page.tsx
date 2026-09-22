import { Tr } from '../../store/locale'
/**
 * Workflows: the two halves of "Marvi did something without me sitting there".
 *
 * The rules say what sets work off. The board says what that work turned into
 * and where it got stuck. They were separate ideas in separate places --
 * cron jobs in one page, sub-agent jobs in a popover that died with the
 * process -- and the question people actually ask spans both: "what is running
 * right now, and why has nothing happened since Tuesday".
 */
import { AutomationsPanel } from './automations-panel'
import { JobsBoard } from './jobs-board'

export function WorkflowsPage(): React.JSX.Element {
  return (
    <div className="wf-page">
      <header className="cron-head">
        <div>
          <h2>
            <Tr text={'Workflows'} />
          </h2>
          <p>
            <Tr
              text={
                'Rules that set work off, and the board of what that work became. Nothing here runs outside the ordinary tool path: a sensitive action still asks you first.'
              }
            />
          </p>
        </div>
      </header>
      <AutomationsPanel />
      <JobsBoard />
    </div>
  )
}
