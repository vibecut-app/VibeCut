import type { SetupData } from './components/Setup'
import type { FaceArea } from './overlayDraw'
import type { Habit, Capabilities, GraphicPiece, ProfileStart, StickerKind, Resource, ResourceFolder, ResourceKind, StartPicks, CutData, CutReport, ExportJob, Job, LengthSlider, LookFit, PrefClass, Project, ProjectMeta, RefCard, RefJob, RefSummary, Session, StyleAnswers, StyleQuestion, TalkState } from './types'

export type MomentInfo = { header: string; key: string; llm: boolean; provider: ChatProvider
  estimate: { tokens_in: number; usd: [number, number] } }
export type MomentAnswer = { reply: string; choices: string[]; ops: Record<string, unknown>[]
  preview: { lines: string[]; skipped: string[] } | null; header: string; cost: number | null; spent: number }
// Who answers the chat: OpenAI on the course key (AI switch on), Claude (its own key), or nobody.
export type ChatProvider = 'openai' | 'claude' | null
export type SharePlatform = { id: 'tiktok' | 'youtube' | 'instagram'; name: string; url: string; where: string; ok: boolean; why: string | null; note: string | null }
export type ShareCover = { t: number; file: string; url: string }
export type PostWords = { line: string; hashtags: string[]; caption: string; chapters: { t: number; name: string }[]; youtube: { title: string; description: string } }
export type OtherVersion = { frame: 'tall' | 'wide'; label: string; for: string }
export type ShareTargets = { shape: 'tall' | 'wide' | 'square' | 'unknown'; seconds: number; platforms: SharePlatform[]; mac: boolean
  other: OtherVersion | null
  post: PostWords; credit: string | null; covers: { t: number; url: string }[]; cover: ShareCover | null }
export type ShareHow = 'download' | 'sheet' | 'caption' | SharePlatform['id']
// posting to the creator's own YouTube channel (backend youtube.py)
export type YouTubeChannel = { id: string; title: string; thumb: string | null }
export type YouTubeState = { configured: boolean; connected: boolean; channel: YouTubeChannel | null; signing_in: boolean; error: string | null; keychain: boolean }
export type YouTubePrep = { confirm: string; channel: YouTubeChannel; title: string; description: string; fit: SharePlatform; seconds: number; file: string
  cover: (ShareCover & { sent: boolean }) | null }
export type YouTubePost = { id: string; stage: 'uploading' | 'done' | 'error' | 'stopped'; sent: number; total: number; progress: number
  title: string; asked: string; privacy: string | null; video: string | null; url: string | null; studio: string | null; error: string | null
  cover: string | null; elapsed: number }
// What one chat message would cost before it's sent, and what AI has cost on this video.
// per_char: what each typed character adds (the estimate already counts base_chars of them).
export type ChatEstimate = { on: boolean; provider: ChatProvider; model: string | null; tokens_in: number
  usd: [number, number]; spent: number; per_char?: number; base_chars?: number }
// A chat answer: the session, or (after Stop) the session unchanged and what the dropped answer cost.
export type ChatResult = Session & { stopped?: boolean; stop_cost?: number | null }

export type ProjectList = { projects: ProjectMeta[]; open: string | null; capabilities: Capabilities }
export type Opened = { project: ProjectMeta; session: Session }

export type AIState = { available: boolean; on: boolean; model: string }
export type AIEstimate = AIState & { moments: number; dollars: number; plan?: number; check?: number }
// One look at the whole cut by the AI (selfcheck.py), priced before it's asked.
export type CheckEstimate = { on: boolean; available: boolean; model: string; shots: number; dollars: number; spent: number }
// A saved recipe (backend recipes.py): an edit the creator liked, offered under "Cut it like"
export type Recipe = {
  id: string; name: string; kind: 'recipe'; line: string; words: string[]
  dress: { format: string | null; look: string | null; music: boolean }
  from: string | null; saved_at: number
}
export type RecipeDraft = { name: string; words: string[]; names: string[] }
export type VibeJob = { id: string; stage: 'learning' | 'done' | 'error'; lines: string[]; error: string | null; done: number; total: number; vibe: string | null; elapsed: number }

export type MakeJob = { id: string; stage: string; line: string; done: number; total: number; error: string | null; elapsed: number }

export type RemixJob = {
  id: string
  stage: 'queued' | 'references' | 'choosing' | 'music' | 'rendering' | 'done' | 'error'
  progress: number
  error: string | null
  lines: string[]
  elapsed: number
  file: string | null
  seconds: number | null
  music: { title: string; bpm: number; credit: string } | null
  fingerprint: string | null
  shots: number | null
}

async function j<T>(res: Promise<Response>): Promise<T> {
  const r = await res
  if (!r.ok) {
    let detail = r.statusText
    try { detail = (await r.json()).detail ?? detail } catch { /* not json */ }
    throw Object.assign(new Error(detail), { status: r.status })
  }
  return r.json()
}

// Every change is a POST, and the server saves the project after each one:
// while none is in flight the draft is saved (the top bar says so).
let inFlight = 0
const savers = new Set<() => void>()
export const saving = {
  get: () => inFlight > 0,
  subscribe: (f: () => void) => { savers.add(f); return () => { savers.delete(f) } },
}
const post = (url: string, body: unknown) => {
  inFlight++
  savers.forEach((f) => f())
  return fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
    .finally(() => { inFlight--; savers.forEach((f) => f()) })
}

// "?visitor" in the address: see My resources as someone without an account
// (resources.who reads the header; it can only take rights away, never give them)
const asVisitor = (): Record<string, string> => {
  try { return new URLSearchParams(window.location.search).has('visitor') ? { 'x-vibecut-visitor': '1' } : {} } catch { return {} }
}
const sendAs = (method: string, url: string, body?: unknown) => {
  inFlight++
  savers.forEach((f) => f())
  return fetch(url, { method, headers: { 'content-type': 'application/json', ...asVisitor() }, body: body === undefined ? undefined : JSON.stringify(body) })
    .finally(() => { inFlight--; savers.forEach((f) => f()) })
}

export const api = {
  // projects: the dashboard's list, and which one is open
  projects: () => j<ProjectList>(fetch('/api/projects')),
  createProject: (name: string) => j<Opened>(post('/api/projects', { name })),
  openProject: (id: string) => j<Opened>(post(`/api/projects/${id}/open`, {})),
  closeProject: () => j<{ projects: ProjectMeta[]; open: null }>(post('/api/projects/close', {})),
  renameProject: (id: string, name: string) =>
    j<{ project: ProjectMeta }>(fetch(`/api/projects/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name }) })),
  deleteProject: (id: string) => j<{ projects: ProjectMeta[]; open: string | null }>(fetch(`/api/projects/${id}`, { method: 'DELETE' })),
  brief: (message: string | null, style?: StyleAnswers, said?: string) =>
    j<Session>(post('/api/project/brief', { message, style: style ?? null, said: said ?? '' })),
  project: () => j<Project>(fetch('/api/project')),
  clear: () => j<Project>(fetch('/api/project', { method: 'DELETE' })),
  locate: (files: { name: string; size: number; mtime: number; relpath: string }[]) =>
    j<{ resolved: Record<string, string>; missing: string[] }>(post('/api/locate', { files })),
  upload: (file: File, relpath: string, batch: string) =>
    j<{ path: string }>(fetch('/api/upload', {
      method: 'POST', body: file,
      headers: { 'x-relpath': encodeURIComponent(relpath), 'x-batch': batch },
    })),
  import: (paths: string[]) => j<Job>(post('/api/import', { paths })),
  job: (id: string) => j<Job>(fetch(`/api/jobs/${id}`)),
  session: () => j<Session>(fetch('/api/session')),
  cut: () => j<CutData>(fetch('/api/cut')),
  override: (target: string, action: string, range?: [number, number]) =>
    j<CutData>(post('/api/cut/override', { target, action, start: range?.[0] ?? null, end: range?.[1] ?? null })),
  approve: () => j<Session>(post('/api/cut/approve', {})),
  // ai_ok: the cost the box showed for this message; on the course key nothing is sent without it
  // t: the moment it's about (edit seconds); rid: names the request so Stop can drop its answer
  chat: (message: string, style?: StyleAnswers, ai_ok?: number | null, t?: number | null, rid?: string) =>
    j<ChatResult>(post('/api/chat', { message, style: style ?? null, ai_ok: ai_ok ?? null, t: t ?? null, rid: rid ?? null })),
  chatStop: (rid: string) => j<{ ok: boolean }>(post('/api/chat/stop', { rid })),
  chatEstimate: (t?: number | null) => j<ChatEstimate>(fetch(t == null ? '/api/chat/estimate' : `/api/chat/estimate?t=${t.toFixed(3)}`)),
  autoBrief: (picks?: { format: string; look: string }) => j<Session>(post('/api/brief/auto', picks ?? {})),
  setup: () => j<SetupData>(fetch('/api/brief/setup')),
  vibeStart: (req: { niche: string; name?: string; links: string[] }) => j<VibeJob>(post('/api/vibes', req)),
  vibeStatus: (id: string) => j<VibeJob>(fetch(`/api/vibes/jobs/${id}`)),
  recipeDraft: () => j<RecipeDraft>(fetch('/api/recipes/draft')),
  saveRecipe: (name: string) => j<{ recipe: Recipe; replaced: boolean }>(post('/api/recipes', { name })),
  renameRecipe: (id: string, name: string) =>
    j<{ recipe: Recipe }>(fetch(`/api/recipes/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name }) })),
  deleteRecipe: (id: string) => j<{ recipes: Recipe[] }>(fetch(`/api/recipes/${encodeURIComponent(id)}`, { method: 'DELETE' })),
  profileGet: () => j<{ profile: Record<string, unknown> | null; at: number | null; cloud: { on: boolean } }>(fetch('/api/profile')),
  profilePut: (profile: Record<string, unknown>) => j<{ profile: Record<string, unknown>; at: number }>(post('/api/profile', { profile })),
  make: (picks: { format: string; look: string; music?: boolean; vibe?: string | null; ai_ok?: number | null }) => j<MakeJob>(post('/api/make', picks)),
  ai: () => j<AIState>(fetch('/api/ai')),
  setAI: (on: boolean) => j<AIState>(post('/api/ai', { on })),
  makeEstimate: () => j<AIEstimate>(fetch('/api/make/estimate')),
  checkEstimate: () => j<CheckEstimate>(fetch('/api/check/estimate')),
  check: (ai_ok: number, rid: string) => j<ChatResult>(post('/api/check', { ai_ok, rid })),
  makeStatus: (id: string) => j<MakeJob>(fetch(`/api/make/${id}`)),
  format: (format: string) => j<Session>(post('/api/format', { format })),
  pile: (clip: string, into: boolean) => j<Session>(post('/api/pile', { clip, into })),
  captions: (on: boolean) => j<Session>(post('/api/captions', { on })),
  bed: (on: boolean) => j<Session>(post('/api/bed', { on })),
  musicVolume: (volume: number) => j<Session>(post('/api/music/volume', { volume })),   // 1 = as placed
  pace: (pace: string) => j<Session>(post('/api/pace', { pace })),
  guess: () => j<{ about: string }>(fetch('/api/brief/guess')),
  suggestions: () => j<{ suggestions: string[]; source: string }>(fetch('/api/brief/suggestions')),
  questions: (message: string) => j<{ questions: StyleQuestion[]; tailored: boolean }>(post('/api/brief/questions', { message })),
  ops: (ops: Record<string, unknown>[], label: string) => j<Session>(post('/api/ops', { ops, label })),
  length: () => j<LengthSlider & { current: number }>(fetch('/api/length')),
  setLength: (seconds: number) => j<Session & { length_note: string }>(post('/api/length', { seconds })),
  smooth: (order: boolean, nudge: boolean) => j<Session>(post('/api/smooth', { order, nudge })),
  cutNotes: () => j<CutReport>(post('/api/cutnotes', {})),
  // chat on pause: what the paused moment is (free), then one message about it (calls the model)
  moment: (t: number) => j<MomentInfo>(post('/api/moment', { t })),
  momentChat: (t: number, message: string, history: { who: 'you' | 'ai'; text: string }[], ai_ok?: number | null) =>
    j<MomentAnswer>(post('/api/moment/chat', { t, message, history, ai_ok: ai_ok ?? null })),
  toggle: (turn: number) => j<Session>(post(`/api/turns/${turn}/toggle`, {})),
  voiceover: (text: string) => j<Session>(post('/api/voiceover', { text })),
  suggest: (req: { id: string; klass: PrefClass | 'rejected'; rule?: string; scope?: string; counter?: string }) => j<Session>(post('/api/preferences/suggest', req)),
  classify: (req: { turn: number; klass: PrefClass; rule?: string; scope?: string; counter?: string; reason?: string }) =>
    j<Session>(post('/api/preferences/classify', req)),
  rule: (id: string, action: 'forget' | 'narrow') => j<Session>(post(`/api/preferences/${id}/${action}`, {})),
  suggestOverlays: (req: { profile: Record<string, unknown>; title?: string; kinds?: string[] }) =>
    j<Session>(post('/api/overlays/suggest', req)),
  // frame: the same edit in the other frame ('tall' / 'wide'), cropped to fill it
  exportCreate: (music: boolean, frame?: 'tall' | 'wide') => j<ExportJob>(post('/api/export', { music, frame: frame ?? null })),
  exportFrame: (id: string, n: number, png: Blob) =>
    j<{ ok: boolean }>(fetch(`/api/export/${id}/frames/${n}`, { method: 'POST', body: png })),
  exportStart: (id: string, schedule: { frame: number | null; start: number; end: number }[], moved = 0) =>
    j<ExportJob>(post(`/api/export/${id}/start`, { schedule, moved })),
  exportFaces: (id: string) => j<{ faces: FaceArea[] }>(fetch(`/api/export/${id}/faces`)),
  exportStatus: (id: string) => j<ExportJob>(fetch(`/api/export/${id}`)),
  exportCancel: (id: string) => j<ExportJob>(post(`/api/export/${id}/cancel`, {})),
  talkStart: (req: { locale: string; script: string }) => j<TalkState>(post('/api/talk', req)),
  talkState: () => j<TalkState>(fetch('/api/talk')),
  talkToggle: (id: string) => j<TalkState>(post('/api/talk/toggle', { id })),
  talkApply: (captions: boolean, profile: Record<string, unknown>) => j<Session>(post('/api/talk/apply', { captions, profile })),
  exportReveal: (id: string) => fetch(`/api/export/${id}/reveal`, { method: 'POST' }),
  exportPhotos: (id: string) => j<{ ok: boolean }>(post(`/api/export/${id}/photos`, {})),
  // where a finished file can go next, each platform checked against it (backend share.py)
  exportShare: (id: string) => j<ShareTargets>(fetch(`/api/export/${id}/share`)),
  exportCover: (id: string, t: number) => j<ShareCover>(post(`/api/export/${id}/cover`, { t })),
  exportShared: (id: string, how: ShareHow) => j<{ ok: boolean }>(post(`/api/export/${id}/shared`, { how })),
  youtube: () => j<YouTubeState>(fetch('/api/youtube')),
  youtubeConnect: () => j<{ url: string }>(post('/api/youtube/connect', {})),
  youtubeDisconnect: () => j<YouTubeState>(post('/api/youtube/disconnect', {})),
  youtubePrepare: (id: string) => j<YouTubePrep>(post(`/api/export/${id}/youtube/prepare`, {})),
  youtubePost: (id: string, req: { confirm: string; title: string; description: string; privacy: string; made_for_kids: boolean | null; cover_t: number | null }) =>
    j<YouTubePost>(post(`/api/export/${id}/youtube`, req)),
  youtubePostStatus: (pid: string) => j<YouTubePost>(fetch(`/api/youtube/posts/${pid}`)),
  youtubePostStop: (pid: string) => j<YouTubePost>(post(`/api/youtube/posts/${pid}/stop`, {})),
  habits: () => j<{ habits: Habit[]; phrases: string[]; last: { id: string; text: string }[] }>(fetch('/api/habits')),
  habitSwitch: (id: string, off: boolean, remake = false) => j<MakeJob & { habit?: Habit }>(post(`/api/habits/${encodeURIComponent(id)}`, { off, remake })),
  // "Which do you like better?" after Make (backend prefer.py)
  prefer: () => j<{ card: import('./types').PreferCard | null; frame: { w: number; h: number } | null }>(fetch('/api/prefer')),
  preferPick: (card: number, pick: number | null) =>
    j<Session & { prefer_said: string; prefer_landed: boolean }>(post(`/api/prefer/${card}`, { pick })),
  exportVerdict: (n: number, wouldPost: boolean, note: string) => j<Session>(post(`/api/exports/${n}/verdict`, { post: wouldPost, note })),
  // Remix: reference reels + the shelf -> one finished short, then the board
  remixStart: (req: { refs: string[]; title?: string; sub?: string; length?: number }) =>
    j<RemixJob>(post('/api/remix', req)),
  remixStatus: (id: string) => j<RemixJob>(fetch(`/api/remix/${id}`)),
  // Borrow a feeling: a reference video's style, learnt and applied as one turn
  refLibrary: () => j<{ references: RefSummary[]; links: boolean }>(fetch('/api/references')),
  refLearn: (source: string) => j<RefJob>(post('/api/references', { source })),
  refJob: (id: string) => j<RefJob>(fetch(`/api/references/jobs/${id}`)),
  refCard: (rid: string) => j<RefCard>(fetch(`/api/references/${rid}`)),
  refLook: (rid: string, strength: 'subtle' | 'full') => j<LookFit>(post(`/api/references/${rid}/look`, { strength })),
  refApply: (rid: string, traits: string[], strength: 'subtle' | 'full') =>
    j<Session>(post(`/api/references/${rid}/apply`, { traits, strength })),
  refForget: (rid: string) => j<{ references: RefSummary[]; links: boolean }>(fetch(`/api/references/${rid}`, { method: 'DELETE' })),
  // My resources: logged out, the folder is empty and saving or using one answers 401.
  // ?visitor in the address shows the folder as someone without an account sees it.
  resources: () => j<ResourceFolder>(fetch('/api/resources', { headers: asVisitor() })),
  saveResource: (kind: ResourceKind, where: { shot?: string | null; after?: string | null; graphic?: string | null } = {}) =>
    j<{ item: Resource; items: Resource[] }>(sendAs('POST', '/api/resources', { kind, shot: where.shot ?? null, after: where.after ?? null, graphic: where.graphic ?? null })),
  useResource: (id: string, where: { shot?: string | null; after?: string | null; t?: number } = {}) =>
    j<Session>(sendAs('POST', `/api/resources/${encodeURIComponent(id)}/use`, { shot: where.shot ?? null, after: where.after ?? null, t: where.t ?? null })),
  // a piece from the Graphic animations tab at the playhead (backend graphics.py)
  addGraphic: (piece: GraphicPiece, t: number, picked: { tint?: string | null; sticker?: StickerKind | null } = {}) =>
    j<Session & { added: string }>(post('/api/graphics', { piece, t, ...picked })),
  renameResource: (id: string, name: string) => j<{ items: Resource[] }>(sendAs('PATCH', `/api/resources/${encodeURIComponent(id)}`, { name })),
  deleteResource: (id: string) => j<{ items: Resource[] }>(sendAs('DELETE', `/api/resources/${encodeURIComponent(id)}`)),
  // your profile's start: asked once after an export, where every next video starts
  profileStart: () => j<ProfileStart>(fetch('/api/profile/start', { headers: asVisitor() })),
  profileStartSave: (picks: StartPicks) => j<ProfileStart>(sendAs('POST', '/api/profile/start', picks)),
  profileSkip: () => j<ProfileStart>(sendAs('POST', '/api/profile/skip', {})),
  useTrack: (trackId: string | null) => j<Session>(post('/api/music/use', { track_id: trackId })),
}
