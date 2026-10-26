import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { CreatorProfile } from './components/CreatorProfile.tsx'
import { Landing } from './components/Landing.tsx'
import { Polish } from './components/Polish.tsx'
import { Projects } from './components/Projects.tsx'
import { go, parseRoute, type Route } from './router.ts'
import './index.css'

// Five places: the projects home, one project's workspace, your profile,
// the finished-video tool, and the landing page (#/welcome). The workspace is remounted per project, so
// nothing of one video leaks into the next.
function Root() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash))
  useEffect(() => {
    const change = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', change)
    return () => window.removeEventListener('hashchange', change)
  }, [])
  switch (route.kind) {
    case 'projects': return <Projects />
    case 'profile': return <CreatorProfile onClose={() => window.history.length > 1 ? window.history.back() : go({ kind: 'projects' })} />
    case 'polish': return <Polish />
    case 'landing': return <Landing />
    case 'project': return <App key={route.id} id={route.id} view={route.view} />
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
