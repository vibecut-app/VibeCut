import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { api } from '../api'
import { fontById } from '../captionFonts'
import { drawGraphics, ensureGraphicFonts, PIECES, tilePiece } from '../graphicDraw'
import type { GraphicPiece, Resource, ResourceFolder, ResourceKind, StickerKind } from '../types'
import { Button, cx } from '../ui'
import { Icon, type IconName } from './icons'

// My resources (sarah, 2026-10-19: "a resources folder so i can save my own
// animations or templates forever", on the left rail, and in the profile).
// The folder's top saves what's on the video now (and so do the Save buttons
// in each tab, where the thing is made); below, what was saved, by kind; one
// click puts it on the video as one undoable turn. Logged out, the folder is
// a card that asks to log in or make an account, and so is every Save.

const ICON: Record<ResourceKind, IconName> = {
  caption: 'text', animation: 'spark', transition: 'split', effect: 'spark', shot: 'adjust', song: 'music', graphic: 'shapes',
}
// where one goes when clicked, said once at the top of its section
const GOES: Record<ResourceKind, string> = {
  caption: 'For every caption',
  animation: 'How every caption arrives',
  transition: 'At the clicked cut, or every cut',
  effect: 'On the clicked shot, or every shot',
  shot: 'On the clicked shot',
  song: 'Under the whole video',
  graphic: 'At the playhead',
}
const SAVE_LABEL: Record<ResourceKind, string> = {
  caption: 'Caption look', animation: 'Animation', transition: 'Transition', effect: 'Effect', shot: 'Shot settings', song: 'Song',
  graphic: 'Graphic animation',
}

/** What can be saved off the video right now: null = ready, else what to do first. */
export type SaveWhy = Record<ResourceKind, string | null>

/** The folder on the left rail. `onUse` absent (the profile page): rename and delete only.
 *  `saveWhy` + `onSave` (the edit screen): the "Save from your video" buttons at the top. */
export function Resources({ folder, error, onUse, onChange, onRetry, saveWhy, onSave }: {
  folder: ResourceFolder | null
  error?: string | null
  onUse?: (r: Resource) => void
  onChange: (items: Resource[]) => void
  onRetry?: () => void
  saveWhy?: SaveWhy
  onSave?: (kind: ResourceKind, why: string | null) => void
}) {
  // a Save button with nothing to keep yet says what to do first, here where it was
  // clicked, for as long as that's still so
  const [asked, setAsked] = useState<ResourceKind | null>(null)
  const said = asked && saveWhy ? saveWhy[asked] : null
  if (error) return (
    <div className="space-y-3 px-1 py-2">
      <p className="font-serif text-[16px] text-zinc-100">Your resources didn’t load: {error}</p>
      {onRetry && <Button onClick={onRetry}>Try again</Button>}
    </div>
  )
  if (!folder) return <p className="px-1 py-2 font-serif text-[16px] text-zinc-300">Opening your folder…</p>
  if (!folder.signed_in) return <LogIn login={folder.signin_url} signup={folder.signup_url ?? folder.signin_url} />
  const kinds = folder.kinds.filter((k) => folder.items.some((x) => x.kind === k.id))
  return (
    <div className="space-y-6">
      {saveWhy && onSave && (
        <section className="space-y-2.5">
          <h3 className="font-serif text-[18px] font-medium text-zinc-100">Save from your video</h3>
          <div className="grid grid-cols-2 gap-2">
            {folder.kinds.map((k) => {
              const why = saveWhy[k.id]
              return (
                <button key={k.id} type="button" onClick={() => { setAsked(k.id); if (!why) onSave(k.id, null) }}
                        title={why ?? `Save this ${SAVE_LABEL[k.id].toLowerCase()} to My resources`}
                        className={cx('flex min-w-0 items-center gap-2 rounded-xl border px-2.5 py-2 text-left font-serif text-[15px]',
                          why ? 'border-dashed border-line text-zinc-300 hover:bg-raised' : 'border-accent/60 bg-accent/6 text-accent hover:bg-accent/12')}>
                  <Icon name={why ? ICON[k.id] : 'plus'} size={17} className="shrink-0" />
                  <span className="min-w-0 truncate">{SAVE_LABEL[k.id]}</span>
                </button>
              )
            })}
          </div>
          {said
            ? <p role="status" className="rounded-lg bg-raised px-3 py-2 font-serif text-[15px] leading-snug text-zinc-100">{said}</p>
            : <p className="font-serif text-[15px] leading-snug text-zinc-300">
                Click a shot or a cut on the timeline first to save just its effect, transition or settings.
              </p>}
        </section>
      )}
      {!folder.items.length ? (
        <section className="space-y-2">
          <h3 className="font-serif text-[18px] font-medium text-zinc-100">Saved</h3>
          <p className="font-serif text-[15px] leading-snug text-zinc-300">
            Nothing saved yet. What you save stays here for every video.
          </p>
        </section>
      ) : <>
        {onUse && <p className="font-serif text-[15px] leading-snug text-zinc-300">Click one to put it on your video.</p>}
        {kinds.map((k) => (
          <section key={k.id} className="space-y-2">
            <header>
              <h3 className="font-serif text-[18px] font-medium text-zinc-100">{k.title}</h3>
              {onUse && <p className="font-serif text-[15px] text-zinc-300">{GOES[k.id]}</p>}
            </header>
            <ul className="space-y-1.5">
              {folder.items.filter((x) => x.kind === k.id).map((r) => (
                <Row key={r.id} r={r} onUse={onUse} onChange={onChange} />
              ))}
            </ul>
          </section>
        ))}
      </>}
    </div>
  )
}

// Logged out (sarah, 2026-10-19: "you need to login to save your resources,
// no account? create one now"). Both buttons go where the Launch work points
// them; until accounts exist they say so. The popup after an export asks the
// same, in its own words.
export function LogIn({ login, signup, title = 'You need to log in to save your resources',
  text = 'Keep your caption looks, animations, transitions, effects and songs, and use them on every video.' }: {
  login: string | null; signup: string | null; title?: string; text?: string
}) {
  const [soon, setSoon] = useState(false)
  const go = (url: string | null) => { if (url) window.location.href = url; else setSoon(true) }
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-line bg-raised px-5 py-6 text-center">
      <span className="grid size-14 place-items-center rounded-2xl bg-accent/12 text-accent"><Icon name="resources" size={30} /></span>
      <h3 className="font-serif text-[20px] leading-tight text-zinc-100">{title}</h3>
      <p className="font-serif text-[15px] leading-snug text-zinc-300">{text}</p>
      <Button variant="primary" size="lg" onClick={() => go(login)}><Icon name="user" size={18} /> Log in</Button>
      <p className="font-serif text-[16px] text-zinc-100">
        No account? <button type="button" onClick={() => go(signup)} className="font-serif text-accent underline underline-offset-2 hover:brightness-110">Create one now</button>
      </p>
      {soon && (
        <p className="font-serif text-[15px] leading-snug text-zinc-100" role="status">
          Accounts are coming soon. Until then, My resources works when VibeCut runs on your own computer.
        </p>
      )}
    </div>
  )
}

function Row({ r, onUse, onChange }: { r: Resource; onUse?: (r: Resource) => void; onChange: (items: Resource[]) => void }) {
  const [mode, setMode] = useState<'show' | 'rename' | 'delete'>('show')
  const [busy, setBusy] = useState(false)
  const [why, setWhy] = useState<string | null>(null)
  const act = async (f: () => Promise<{ items: Resource[] }>) => {
    setBusy(true); setWhy(null)
    try { onChange((await f()).items); setMode('show') } catch (e) { setWhy((e as Error).message) } finally { setBusy(false) }
  }
  const icon = (name: IconName, label: string, onClick: () => void) => (
    <button type="button" title={label} aria-label={`${label} ${r.name}`} onClick={onClick}
            className="grid size-9 shrink-0 place-items-center rounded-lg text-zinc-300 hover:bg-raised hover:text-zinc-100">
      <Icon name={name} size={18} />
    </button>
  )
  return (
    <li className="rounded-xl border border-line bg-panel">
      {mode === 'rename' ? (
        <Rename name={r.name} busy={busy} onDone={(name) => (name && name !== r.name ? act(() => api.renameResource(r.id, name)) : setMode('show'))} />
      ) : (
        <div className="flex items-center gap-1 pr-1">
          {onUse ? (
            <button type="button" onClick={() => onUse(r)} title={`Put “${r.name}” on your video`}
                    className="flex min-w-0 flex-1 items-center gap-3 rounded-l-xl px-2 py-2 text-left hover:bg-raised">
              <Tile r={r} /><span className="min-w-0 flex-1 truncate font-serif text-[16px] text-zinc-100">{r.name}</span>
            </button>
          ) : (
            <span className="flex min-w-0 flex-1 items-center gap-3 px-2 py-2">
              <Tile r={r} /><span className="min-w-0 flex-1 truncate font-serif text-[16px] text-zinc-100">{r.name}</span>
            </span>
          )}
          {icon('pencil', 'Rename', () => setMode('rename'))}
          {icon('trash', 'Delete', () => setMode('delete'))}
        </div>
      )}
      {mode === 'delete' && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2">
          <span className="min-w-0 flex-1 font-serif text-[15px] text-zinc-100">Delete it from your resources?</span>
          <Button size="sm" variant="danger" disabled={busy} onClick={() => act(() => api.deleteResource(r.id))}>Delete</Button>
          <Button size="sm" onClick={() => setMode('show')}>Keep</Button>
        </div>
      )}
      {why && <p className="border-t border-line px-3 py-2 font-serif text-[15px] text-rose-300">{why}</p>}
    </li>
  )
}

// No <form>: the profile page is one, and a form inside a form submits the outer one.
function Rename({ name, busy, onDone }: { name: string; busy: boolean; onDone: (name: string | null) => void }) {
  const [v, setV] = useState(name)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { ref.current?.select() }, [])
  return (
    <div className="flex items-center gap-2 p-2">
      <input ref={ref} value={v} maxLength={60} disabled={busy} aria-label="New name" onChange={(e) => setV(e.target.value)}
             onKeyDown={(e) => {
               if (e.key === 'Enter') { e.preventDefault(); onDone(v.trim()) }
               if (e.key === 'Escape') onDone(null)
             }}
             className="min-w-0 flex-1 rounded-lg border border-line bg-ink px-2.5 py-1.5 font-serif text-[16px] text-zinc-100 outline-none focus:border-accent/60" />
      <Button size="sm" variant="primary" disabled={busy || !v.trim()} onClick={() => onDone(v.trim())}>Save</Button>
      <Button size="sm" onClick={() => onDone(null)}>Cancel</Button>
    </div>
  )
}

// A caption look is shown in its own letters; everything else by what it is.
function Tile({ r }: { r: Resource }) {
  if (r.kind === 'caption') {
    const v = r.value as { typeface?: string; text_color?: string; outline?: { color: string; width: number } | null
      shadow?: { color: string; opacity: number } | null; backdrop?: { color: string; opacity: number } | null }
    const f = fontById(v.typeface)
    const style: CSSProperties = {
      fontFamily: f?.family, fontWeight: f?.weight ?? 600, color: v.text_color ?? '#ffffff',
      WebkitTextStroke: v.outline?.width ? `1.5px ${v.outline.color}` : undefined,
      textShadow: v.shadow?.opacity ? `1px 2px 3px ${v.shadow.color}` : undefined,
      background: v.backdrop?.opacity ? v.backdrop.color : undefined,
    }
    return (
      <span className="grid size-11 shrink-0 place-items-center rounded-lg bg-[#1d1d22]">
        <span className="rounded px-1 text-[19px] leading-none" style={style}>Aa</span>
      </span>
    )
  }
  if (r.kind === 'graphic' && (r.value.piece as string) in PIECES) return <GraphicTile v={r.value} />
  return (
    <span className={cx('grid size-11 shrink-0 place-items-center rounded-lg bg-accent/10 text-accent')}>
      <Icon name={ICON[r.kind]} size={20} />
    </span>
  )
}

// a saved graphic animation, still, as it looks once it's in
function GraphicTile({ v }: { v: Record<string, unknown> }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    let alive = true
    const draw = () => {
      const c = ref.current
      const ctx = c?.getContext('2d')
      if (!c || !ctx || !alive) return
      const g = tilePiece(v.piece as GraphicPiece, 1.35, v.tint as string | undefined, v.sticker as StickerKind | undefined)
      ctx.clearRect(0, 0, c.width, c.height)
      drawGraphics(ctx, c.width, c.height, [g], PIECES[g.piece].life * 0.55)
    }
    draw()
    ensureGraphicFonts().then(draw)
    return () => { alive = false }
  }, [v])
  return <canvas ref={ref} width={88} height={88} className="size-11 shrink-0 rounded-lg bg-[#3a3f47]" />
}
