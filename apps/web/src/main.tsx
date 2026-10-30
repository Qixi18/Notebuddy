import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import App from './App'
import '@fontsource-variable/noto-sans-sc/wght.css'
import 'katex/dist/katex.min.css'
import './styles.css'
import './redesign.css'
import './course-assistant.css'
import './assistant-workspace.css'
import './features/home/home.css'
import './features/home/home-courses.css'
import './garden-theme.css'
import './features/forest/botanical-surfaces.css'
import './dialogs.css'

const router = createBrowserRouter([{ path: '*', element: <App /> }])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
