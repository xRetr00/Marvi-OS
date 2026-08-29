import {
  Activity,
  Archive,
  ArrowDownToLine,
  ArrowLeft,
  ArrowUp,
  AudioLines,
  Blocks,
  Box,
  BrainCircuit,
  Braces,
  CalendarClock,
  Check,
  ChevronDown,
  Copy,
  Download,
  Fingerprint,
  Info,
  Layers3,
  LayoutDashboard,
  Link2,
  Maximize2,
  MessageSquare,
  Mic,
  Minus,
  Network,
  PanelLeft,
  Paperclip,
  Pencil,
  Plus,
  RefreshCw,
  ScanEye,
  ScanLine,
  Search,
  ServerCog,
  Settings,
  SlidersHorizontal,
  Square,
  SquareStack,
  TimerReset,
  UserRoundPlus,
  Volume2,
  Wrench,
  X,
  type LucideIcon,
  type LucideProps
} from 'lucide-react'

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
  | 'connectors'
  | 'mcp'
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
  | 'back'
  | 'search'
  | 'plus'
  | 'edit'
  | 'archive'
  | 'paperclip'
  | 'microphone'
  | 'speaker'
  | 'regenerate'

/**
 * Semantic names are stable Marvi UI contracts; the drawings come entirely
 * from Lucide. Keeping this adapter means callers do not depend on vendor icon
 * names and a future SDK update remains one audited mapping instead of dozens
 * of component edits.
 */
export const ABSTRACT_ICONS: Readonly<Record<AbstractIconName, LucideIcon>> = Object.freeze({
  overview: LayoutDashboard,
  voice: AudioLines,
  chat: MessageSquare,
  vision: ScanEye,
  room: ScanLine,
  activity: Activity,
  identity: Fingerprint,
  memory: Layers3,
  mind: BrainCircuit,
  providers: Network,
  models: Box,
  accounts: UserRoundPlus,
  skills: Braces,
  plugins: Blocks,
  connectors: Link2,
  mcp: ServerCog,
  preferences: SlidersHorizontal,
  schedules: CalendarClock,
  maintenance: Wrench,
  about: Info,
  version: ArrowDownToLine,
  timing: TimerReset,
  settings: Settings,
  minimize: Minus,
  maximize: Maximize2,
  restore: SquareStack,
  close: X,
  panel: PanelLeft,
  send: ArrowUp,
  stop: Square,
  copy: Copy,
  check: Check,
  download: Download,
  down: ChevronDown,
  back: ArrowLeft,
  search: Search,
  plus: Plus,
  edit: Pencil,
  archive: Archive,
  paperclip: Paperclip,
  microphone: Mic,
  speaker: Volume2,
  regenerate: RefreshCw
})

export function AbstractIcon({
  name,
  size = 18,
  ...props
}: { name: AbstractIconName; size?: number } & Omit<LucideProps, 'name'>): React.JSX.Element {
  const Icon = ABSTRACT_ICONS[name]
  return (
    <Icon
      aria-hidden="true"
      size={size}
      strokeWidth={1.6}
      vectorEffect="non-scaling-stroke"
      {...props}
    />
  )
}
