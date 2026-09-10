import { createRoot } from 'react-dom/client'
import { Chat } from './chat'
import './assets/base.css'
import './assets/main.css'
createRoot(document.getElementById('root')!).render(<Chat onExit={() => {}} />)
