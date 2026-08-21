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

const paths: Record<AbstractIconName, React.ReactNode> = {
  overview: <path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" />,
  voice: <path d="M3 12h3l2-6 3 12 3-9 2 6 2-3h3" />,
  chat: <path d="M4 5h13v10H9l-4 4v-4H4zM10 9h10v8h-3l-3 3v-3" />,
  vision: <path d="M2.5 12s3.6-6 9.5-6 9.5 6 9.5 6-3.6 6-9.5 6-9.5-6-9.5-6zM12 9v6M9 12h6" />,
  room: <path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5M8 12h8M12 8v8" />,
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
  preferences: <path d="M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M6 14v6" />,
  schedules: <path d="M12 7v5l3 2M5 3v4M19 3v4M4 6h16v15H4z" />,
  maintenance: <path d="M14 5a5 5 0 0 0-6 6L3 16l5 5 5-5a5 5 0 0 0 6-6l-4 2-3-3z" />,
  about: <path d="M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 10v7M12 7h.01" />,
  version: <path d="M12 3v12M7 10l5 5 5-5M4 20h16" />,
  timing: <path d="M12 7v5l3 2M12 3a9 9 0 1 0 9 9M17 3h4v4" />
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
