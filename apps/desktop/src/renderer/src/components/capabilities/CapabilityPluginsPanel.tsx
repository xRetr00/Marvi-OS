import { t } from '../../store/locale'
import { Blocks } from 'lucide-react'

import { ControlEmpty, ControlPage, ControlSection } from '../control-surface'

/**
 * Capabilities > Plugins: third-party/extension plugins a user installs,
 * distinct from Settings > Plugins (Marvi's own bundled services, e.g. Smart
 * Room). No install system exists for this surface yet — this is the empty
 * shell, sized and shaped like Connectors and MCP so the page slots into the
 * group cleanly once one lands, rather than a stub with different bones.
 */
export function CapabilityPluginsPanel(): React.JSX.Element {
  return (
    <ControlPage
      className="capabilities-page"
      description={t(
        "Third-party plugins that extend what Marvi can do. Distinct from Settings > Plugins, which manages Marvi's own bundled services."
      )}
      title={t('Plugins')}
    >
      <ControlSection icon={Blocks} title={t('Installed plugins')}>
        <ControlEmpty
          description={t(
            "There is no third-party plugin catalog yet. Marvi's own services, like Smart Room, are managed from Settings > Plugins."
          )}
          icon={Blocks}
          title={t('No plugins installed')}
        />
      </ControlSection>
    </ControlPage>
  )
}
