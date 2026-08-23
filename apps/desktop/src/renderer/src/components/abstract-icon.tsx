import type { SVGProps } from 'react'

export type AbstractIconName =
  | 'overview'
  | 'voice'
  | 'chat'
  | 'vision'
  | 'room'
  | 'activity'
  | 'identity'
  | 'memory'
  | 'mind'
  | 'providers'
  | 'models'
  | 'accounts'
  | 'skills'
  | 'plugins'
  | 'preferences'
  | 'schedules'
  | 'maintenance'
  | 'about'
  | 'version'
  | 'timing'
  | 'settings'
  | 'minimize'
  | 'maximize'
  | 'restore'
  | 'close'
  | 'panel'
  | 'send'
  | 'stop'
  | 'copy'
  | 'check'
  | 'download'
  | 'down'
  | 'plus'
  | 'edit'
  | 'archive'
  | 'paperclip'
  | 'microphone'
  | 'speaker'
  | 'regenerate'

const paths: Record<AbstractIconName, React.ReactNode> = {
  overview: <path d="M3.5 4.5h7v6h-7zM13.5 4.5h7v3h-7zM13.5 10.5h7v9h-7zM3.5 13.5h7v6h-7z" />,
  voice: <path d="M4 11v2M7 8v8M10 4v16M13 7v10M16 9v6M19 11v2M2 12h2M20 12h2" />,
  chat: <path d="M3.5 4.5h14v11H9l-5.5 4v-4zM8 8.5h5M8 11.5h7M18 8.5h2.5v10h-4l-2.5 2v-5" />,
  vision: <path d="M2.5 12s3.6-6 9.5-6 9.5 6 9.5 6-3.6 6-9.5 6-9.5-6-9.5-6zM12 9v6M9 12h6" />,
  room: (
    <path d="M3.5 9V3.5H9M15 3.5h5.5V9M20.5 15v5.5H15M9 20.5H3.5V15M8 12h8M12 8v8M6 6l2 2M18 6l-2 2M6 18l2-2M18 18l-2-2" />
  ),
  activity: <path d="M3 13h4l2-6 4 11 3-8 2 3h3" />,
  identity: (
    <path d="M12 3a6 6 0 0 0-6 6v3M12 6a3 3 0 0 0-3 3v7M15 9v4a8 8 0 0 1-2 5M18 9v4a11 11 0 0 1-3 7M6 15a12 12 0 0 0 1 4" />
  ),
  memory: <path d="m12 3 8 4-8 4-8-4 8-4zM4 12l8 4 8-4M4 17l8 4 8-4" />,
  mind: (
    <path d="M12 7a5 5 0 1 0 5 5M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M19.1 4.9 17 7" />
  ),
  providers: (
    <path d="M5 6h6v5H5zM13 13h6v5h-6zM11 8.5h4a3 3 0 0 1 3 3V13M9 11v3a2 2 0 0 0 2 2h2" />
  ),
  models: <path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3zM4 7.5l8 4.5 8-4.5M12 12v9" />,
  accounts: <path d="M8 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 20c0-4 2-6 6-6s6 2 6 6M16 8h6M19 5v6" />,
  skills: <path d="M8 5H4v14h4M16 5h4v14h-4M10 16l4-8" />,
  plugins: <path d="M9 3v5H4v8h5v5h6v-5h5V8h-5V3z" />,
  preferences: <path d="M3 6h9M16 6h5M12 3v6M3 12h3M10 12h11M6 9v6M3 18h12M19 18h2M15 15v6" />,
  schedules: <path d="M12 7v5l3 2M5 3v4M19 3v4M4 6h16v15H4z" />,
  maintenance: <path d="M14 5a5 5 0 0 0-6 6L3 16l5 5 5-5a5 5 0 0 0 6-6l-4 2-3-3z" />,
  about: <path d="M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 10v7M12 7h.01" />,
  version: <path d="M12 3v12M7 10l5 5 5-5M4 20h16" />,
  timing: <path d="M12 7v5l3 2M12 3a9 9 0 1 0 9 9M17 3h4v4" />,
  settings: (
    <path d="M12 3.2v2.1M12 18.7v2.1M3.2 12h2.1M18.7 12h2.1M5.8 5.8l1.5 1.5M16.7 16.7l1.5 1.5M18.2 5.8l-1.5 1.5M7.3 16.7l-1.5 1.5M12 7.4a4.6 4.6 0 1 0 0 9.2 4.6 4.6 0 0 0 0-9.2zM12 10.2a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6z" />
  ),
  minimize: <path d="M5 16.5h14" />,
  maximize: <path d="M5.5 5.5h13v13h-13zM5.5 9h13" />,
  restore: <path d="M8 5.5h10.5V16H16M5.5 8H16v10.5H5.5z" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  panel: <path d="M4 4h16v16H4zM9 4v16M12 8h5M12 12h5M12 16h3" />,
  send: <path d="m4 5 16 7-16 7 3-7-3-7zM7 12h13" />,
  stop: <path d="M6.5 6.5h11v11h-11z" />,
  copy: <path d="M8 8h11v11H8zM5 16H4V5h11v1" />,
  check: <path d="m5 12 4.5 4.5L19 7" />,
  download: <path d="M12 3v12M7.5 10.5 12 15l4.5-4.5M4 20h16" />,
  down: <path d="m6 9 6 6 6-6" />,
  plus: <path d="M12 5v14M5 12h14" />,
  edit: <path d="M5 19h4L19 9l-4-4L5 15v4zM13.5 6.5l4 4" />,
  archive: <path d="M4 7h16v13H4zM3 4h18v3H3zM9 11h6" />,
  paperclip: (
    <path d="m8 12 6.5-6.5a4 4 0 0 1 5.5 5.8L10.5 21a6 6 0 0 1-8.5-8.5l9-9M6 15l8.5-8.5" />
  ),
  microphone: (
    <path d="M8 5a4 4 0 0 1 8 0v7a4 4 0 0 1-8 0V5zM5 11v1a7 7 0 0 0 14 0v-1M12 19v3M8 22h8" />
  ),
  speaker: <path d="M4 10h4l5-4v12l-5-4H4zM16 9a5 5 0 0 1 0 6M18.5 6.5a9 9 0 0 1 0 11" />,
  regenerate: <path d="M20 8V3l-2 2a9 9 0 1 0 2 10M20 3h-5" />
}

export function AbstractIcon({
  name,
  size = 18,
  ...props
}: { name: AbstractIconName; size?: number } & Omit<
  SVGProps<SVGSVGElement>,
  'name'
>): React.JSX.Element {
  return (
    <svg aria-hidden="true" fill="none" height={size} viewBox="0 0 24 24" width={size} {...props}>
      <g stroke="currentColor" strokeLinecap="square" strokeLinejoin="miter" strokeWidth="1.35">
        {paths[name]}
      </g>
    </svg>
  )
}
