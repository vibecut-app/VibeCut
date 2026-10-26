// The app's few places, as hash routes. No library: five screens, one
// parameter. #/welcome is the page that sells the product. Old links (#profile, #polish, #tools) still land somewhere sensible.

export type Route =
  | { kind: 'projects' }
  | { kind: 'project'; id: string; view: 'story' | 'frames' }
  | { kind: 'profile' }
  | { kind: 'polish' }
  | { kind: 'landing' }

export function parseRoute(hash: string): Route {
  const h = hash.replace(/^#\/?/, '').replace(/\/+$/, '')
  if (h === '' || h === 'projects' || h === 'tools') return { kind: 'projects' }
  if (h === 'profile') return { kind: 'profile' }
  if (h === 'polish') return { kind: 'polish' }
  if (h === 'welcome' || h.startsWith('welcome#')) return { kind: 'landing' }
  const m = h.match(/^p\/([0-9a-f]{12})(?:\/(frames|story))?$/)
  if (m) return { kind: 'project', id: m[1], view: m[2] === 'frames' ? 'frames' : 'story' }
  return { kind: 'projects' }
}

export function routeHash(r: Route): string {
  switch (r.kind) {
    case 'projects': return '#/'
    case 'profile': return '#/profile'
    case 'polish': return '#/polish'
    case 'landing': return '#/welcome'
    case 'project': return `#/p/${r.id}${r.view === 'frames' ? '/frames' : ''}`
  }
}

export function go(r: Route): void {
  const h = routeHash(r)
  if (window.location.hash !== h) window.location.hash = h
}
