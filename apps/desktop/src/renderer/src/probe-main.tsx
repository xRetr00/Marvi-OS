// TEMP: mounts only the chat page, client-side, to isolate it from the shell.
import { createRoot } from 'react-dom/client'
import { Chat } from './chat'
import './assets/base.css'
import './assets/main.css'

createRoot(document.getElementById('root')!).render(<Chat onExit={() => {}} />)
