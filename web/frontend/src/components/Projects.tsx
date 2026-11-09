import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { fromDataTransfer, fromInput, handOff, handOffRefs, mergePicked, type Picked } from '../drop'
import { bytes, dur } from '../format'
import { loadProfile } from '../profile'
import { go } from '../router'
import type { ExportJob, ProjectMeta } from '../types'
import { ago, Button, Confirm, cx, Dialog, Field, inputCls, Notice, Wordmark } from '../ui'
import { Btn, Label, Mark, NOISE, Ticks } from './Landing'
import { SharePanel } from './SharePanel'

// Home: every video you're making, and where each one stands. A new video
// starts from its clips, not from a name (sarah, 2026-10-06: "just be able to
// drag or select clips, then a confirm create button"): drop or pick clips,
// look at what's picked, Create. It's named from the day it was filmed.
// Under the box, your recent videos (sarah, 2026-10-27), so a return visit
// opens on what you made: each as its own picture, with Open and Share.
//
// The look is the landing page's (sarah, 2026-11-09: Home "doesn't match the
// aesthetics of the landing page", then "all five" of the ideas): its dark
// palette with film grain and a soft gold glow, a big serif headline with one
// italic turn, the gold button, the drop box framed with crop marks, sections
// numbered like a contents line, and each video upright and whole like the
// landing page's carousel, tapped to open. The editor stays bright.

const STAGE_WORDS: Record<ProjectMeta['stage'], string> = {
  footage: 'Footage', brief: 'Getting ready', cut: 'Getting ready', story: 'Editing', exported: 'Exported',
}

const CSS = `
.home-glow { background: radial-gradient(55% 55% at 50% 0%, rgba(255,217,61,.08), transparent 70%); }
.home-grain { opacity: .06; background-image: ${NOISE}; }
.home-card { transition: transform .4s cubic-bezier(.34,1.56,.64,1), filter .4s; }
.home-card:hover { transform: translateY(-4px) scale(1.02); filter: brightness(1.08); }
@media (prefers-reduced-motion: reduce) { .home-card { transition: none; } .home-card:hover { transform: none; } }
`

export function Projects() {
  const [list, setList] = useState<ProjectMeta[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [rename, setRename] = useState<ProjectMeta | null>(null)
  const [remove, setRemove] = useState<ProjectMeta | null>(null)
  const [sharing, setSharing] = useState<ProjectMeta | null>(null)
  const mine = (() => { try { return loadProfile(window.localStorage).profile.name.trim() } catch { return '' } })()
  const initial = mine.charAt(0).toUpperCase() || '☺'
  // Home talks to the person (sarah: "hello, Sarah, like talk to the user"):
  // the first name on their profile, the one behind the avatar.
  const hello = mine.split(/\s+/)[0]

  // Videos saved before Home showed them get their picture filled in the
  // background; ask again until that's done.
  const again = useRef<number | undefined>(undefined)
  const load = () => api.projects().then((r) => {
    setList(r.projects); setError(null)
    window.clearTimeout(again.current)
    if (r.filling) again.current = window.setTimeout(load, 2500)
  }).catch((e) => setError((e as Error).message))
  useEffect(() => { load(); return () => window.clearTimeout(again.current) }, [])

  const open = async (p: ProjectMeta) => {
    try { await api.openProject(p.id); go({ kind: 'project', id: p.id, view: 'story' }) }
    catch (e) { setError((e as Error).message) }
  }
  const [picked, setPicked] = useState<Picked[]>([])
  const [links, setLinks] = useState('')
  const [creating, setCreating] = useState(false)
  const create = async () => {
    if (!picked.length || creating) return
    setCreating(true)
    try {
      const r = await api.createProject('')
      handOff(picked)
      handOffRefs(links.split(/\s+/).map((x) => x.trim()).filter(Boolean))
      go({ kind: 'project', id: r.project.id, view: 'story' })
    } catch (e) { setError((e as Error).message); setCreating(false) }
  }

  // The whole page takes a drop, not just the box.
  const [dragging, setDragging] = useState(false)
  useEffect(() => {
    let depth = 0
    const isFiles = (e: DragEvent) => !!e.dataTransfer?.types.includes('Files')
    const enter = (e: DragEvent) => { if (isFiles(e)) { depth++; setDragging(true) } }
    const leave = (e: DragEvent) => { if (isFiles(e) && --depth <= 0) { depth = 0; setDragging(false) } }
    const over = (e: DragEvent) => { if (isFiles(e)) e.preventDefault() }
    const drop = async (e: DragEvent) => {
      if (!isFiles(e)) return
      e.preventDefault(); depth = 0; setDragging(false)
      const more = await fromDataTransfer(e.dataTransfer!)
      setPicked((p) => mergePicked(p, more))
    }
    window.addEventListener('dragenter', enter); window.addEventListener('dragleave', leave)
    window.addEventListener('dragover', over); window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter); window.removeEventListener('dragleave', leave)
      window.removeEventListener('dragover', over); window.removeEventListener('drop', drop)
    }
  }, [])

  return (
    <div className="on-video relative flex h-full flex-col overflow-hidden bg-ink font-sans text-zinc-100 antialiased">
      <style>{CSS}</style>
      <div aria-hidden className="home-grain pointer-events-none fixed inset-0 z-50" />
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-ink px-4">
        <Mark className="size-6" />
        <Wordmark className="text-[20px]" />
        <div className="flex-1" />
        {/* Polish (#polish) still works by its address; home doesn't offer it
            (sarah, 2026-10-06: no need for it there). */}
        <button type="button" title="Your profile" aria-label="Your profile" onClick={() => go({ kind: 'profile' })}
                className="grid size-8 place-items-center rounded-full bg-zinc-700 font-serif text-[15px] font-semibold text-zinc-100 ring-1 ring-zinc-500/40 hover:ring-accent">{initial}</button>
      </header>

      <main className="relative min-h-0 flex-1 overflow-y-auto">
        <div aria-hidden className="home-glow pointer-events-none absolute inset-x-0 top-0 h-[900px]" />
        <div className="relative mx-auto max-w-[1100px] px-4 py-10 sm:px-6">
          <h1 className="font-serif text-[40px] font-normal leading-[1.04] tracking-[-0.02em] text-zinc-100 sm:text-[64px]">
            {greeting(hello)}<br /><em className="font-serif italic text-zinc-400">What did you film?</em>
          </h1>
          {error && <Notice tone="bad" className="mt-4">{error} <button type="button" className="underline" onClick={load}>Try again</button></Notice>}

          <Start picked={picked} dragging={dragging} creating={creating} compact={!!list?.length}
                 links={links} onLinks={setLinks}
                 onAdd={(more) => setPicked((p) => mergePicked(p, more))}
                 onRemove={(i) => setPicked((p) => p.filter((_, k) => k !== i))}
                 onCreate={create} />

          {list === null ? (
            <p className="mt-10 font-serif text-[17px] text-zinc-200">Loading…</p>
          ) : list.length === 0 ? null : (
            <section className="mt-14" aria-labelledby="recent-title">
              <h2 id="recent-title"><Label n="01">Your recent videos</Label></h2>
              <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-5 lg:grid-cols-4">
                {list.map((p) => <Card key={p.id} p={p} onOpen={() => open(p)} onShare={() => setSharing(p)}
                                       onRename={() => setRename(p)} onDelete={() => setRemove(p)} />)}
              </div>
            </section>
          )}

        </div>
      </main>

      {sharing && <ShareVideo p={sharing} onClose={() => setSharing(null)} />}
      {rename && <RenameProject p={rename} onClose={() => setRename(null)} onDone={() => { setRename(null); load() }} />}
      {remove && (
        <Confirm title={`Delete “${remove.name}”?`} action="Delete the project" danger onNo={() => setRemove(null)}
                 text={<>Only the project is removed: its story, its edits and its history. Your clips and any exported files stay exactly where they are.</>}
                 onYes={async () => { try { await api.deleteProject(remove.id); setRemove(null); load() } catch (e) { setError((e as Error).message); setRemove(null) } }} />
      )}
    </div>
  )
}

// One video, upright and whole, the way it will be watched: its picture
// fills the card (the clip's clearest frame at full size, or the cover the
// creator chose to post with), with where it stands, its name and date over
// it. Tapping the card opens it; Share sits on the picture once there's an
// exported file to share.
function Card({ p, onOpen, onShare, onRename, onDelete }: {
  p: ProjectMeta; onOpen: () => void; onShare: () => void; onRename: () => void; onDelete: () => void
}) {
  const [menu, setMenu] = useState(false)
  const v = p.video ?? null
  // the next picture when one can't be read (a clip that has moved)
  const pics = [v?.chosen ? v.poster : null, p.picture, v?.poster, p.poster, p.cover].filter((x): x is string => !!x)
  const [miss, setMiss] = useState(0)
  useEffect(() => setMiss(0), [pics.join('|')])
  const pic = pics[miss] ?? null
  const seconds = v?.seconds ?? p.seconds ?? null
  // "Exported" is already said above the name
  const line = v?.at ? ago(v.at)
    : p.clips ? `${p.clips} clip${p.clips === 1 ? '' : 's'} · ${ago(p.updated)}` : 'No clips yet'
  const chip = 'rounded-full border border-white/35 bg-black/45 text-white backdrop-blur-sm transition-colors hover:bg-black/70'
  return (
    <article className="home-card group relative aspect-[9/16] overflow-hidden rounded-[14px] border border-white/10 bg-raised shadow-xl">
      <button type="button" onClick={onOpen} aria-label={`Open ${p.name}`}
              className="absolute inset-0 block text-left focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-[#FFD93D]">
        {pic && <img src={pic} alt="" onError={() => setMiss((m) => m + 1)} className="absolute inset-0 size-full object-cover" />}
        <span aria-hidden className="absolute inset-x-0 top-0 h-1/5 bg-gradient-to-b from-black/45 to-transparent" />
        <span aria-hidden className="absolute inset-x-0 bottom-0 h-3/5 bg-gradient-to-t from-black/85 via-black/40 to-transparent" />
        <span className="absolute inset-x-3 bottom-3 block">
          <span className="block truncate text-[11px] font-semibold uppercase tracking-[0.16em] text-white/90">
            {STAGE_WORDS[p.stage]}{seconds ? <span className="tabular-nums"> · {dur(seconds)}</span> : null}
          </span>
          <span className="mt-1 block truncate font-serif text-[22px] leading-tight text-white">{p.name}</span>
          <span className="block truncate font-serif text-[15px] text-white/80">{line}</span>
        </span>
      </button>
      <div className="absolute right-2.5 top-2.5 flex gap-1.5">
        {v && <button type="button" onClick={onShare} className={cx(chip, 'px-3 py-0.5 font-serif text-[15px]')}>Share</button>}
        <button type="button" aria-label="Rename or delete" title="Rename or delete" onClick={() => setMenu((m) => !m)}
                className={cx(chip, 'grid size-7 place-items-center text-[15px] leading-none')}>⋯</button>
      </div>
      {menu && (
        <div className="absolute right-2.5 top-11 z-10 w-36 rounded-lg border border-line bg-panel p-1 shadow-xl" onMouseLeave={() => setMenu(false)}>
          <button type="button" onClick={() => { setMenu(false); onRename() }} className="block w-full rounded-md px-2.5 py-1.5 text-left font-serif text-[15px] text-zinc-100 hover:bg-raised">Rename</button>
          <button type="button" onClick={() => { setMenu(false); onDelete() }} className="block w-full rounded-md px-2.5 py-1.5 text-left font-serif text-[15px] text-rose-200 hover:bg-rose-500/10">Delete…</button>
        </div>
      )}
    </article>
  )
}

// Share straight from Home: the video plays at the top so it's the right
// one, then the same Share box as after an export (download, Photos, the
// share sheet, each platform checked against the file).
function ShareVideo({ p, onClose }: { p: ProjectMeta; onClose: () => void }) {
  const [job, setJob] = useState<ExportJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { api.shareProject(p.id).then(setJob, (e) => setError((e as Error).message)) }, [p.id])
  const tall = !!job && job.size.h > job.size.w
  return (
    <Dialog title={`Share “${p.name}”`} onClose={onClose} width={520}>
      {job ? <>
        <video src={`/api/export/${job.id}/file`} poster={p.video?.poster} controls playsInline preload="metadata"
               className={cx('mx-auto block rounded-lg bg-black', tall ? 'h-[36vh] max-h-[340px]' : 'w-full')} />
        <SharePanel job={job} caption={p.name} />
      </> : error ? <Notice tone="bad">{error}</Notice>
        : <p className="font-serif text-[17px] text-zinc-200">Getting it ready…</p>}
    </Dialog>
  )
}

// The way in: drop clips or a folder anywhere on the page, or choose them.
// What's picked shows as a row (remove one with ×); Create makes the video.
function Start({ picked, dragging, creating, compact, links, onLinks, onAdd, onRemove, onCreate }: {
  picked: Picked[]; dragging: boolean; creating: boolean; compact: boolean
  links: string; onLinks: (s: string) => void
  onAdd: (p: Picked[]) => void; onRemove: (i: number) => void; onCreate: () => void
}) {
  const hasLinks = links.trim().length > 0
  const files = useRef<HTMLInputElement>(null)
  const folder = useRef<HTMLInputElement>(null)
  const size = picked.reduce((n, p) => n + p.file.size, 0)
  const pick = (fl: FileList | null) => { if (fl) onAdd(fromInput(fl)) }
  return (
    <>
    <div className={cx('relative mt-10 rounded-[10px] border text-center transition-colors',
      dragging ? 'border-[#FFD93D] bg-[#FFD93D]/5' : 'border-zinc-600', compact && !picked.length ? 'px-6 py-9' : 'p-10')}>
      <Ticks />
      {/* A browser's picker takes clips or a folder, never both, so two buttons.
          (sarah: a phone version will only need Add clips.) */}
      {/* @ts-expect-error -- non-standard but supported everywhere that matters */}
      <input ref={folder} type="file" className="hidden" webkitdirectory="" multiple onChange={(e) => { pick(e.target.files); e.target.value = '' }} />
      <input ref={files} type="file" className="hidden" multiple accept=".mp4,.mov,video/mp4,video/quicktime"
             onChange={(e) => { pick(e.target.files); e.target.value = '' }} />
      {!picked.length ? (
        <>
          <h2 className={cx('font-serif text-zinc-100', compact ? 'text-[22px]' : 'text-[26px]')}>{dragging ? 'Drop them here' : 'Start with your clips'}</h2>
          <p className="mt-2 font-serif text-[17px] text-zinc-200">Drag clips / folder here</p>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <Btn onClick={() => files.current?.click()}>Add clips</Btn>
            <Btn ghost onClick={() => folder.current?.click()}>Add folder</Btn>
          </div>
        </>
      ) : (
        <>
          <h2 className="font-serif text-[22px] text-zinc-100">{picked.length} clip{picked.length === 1 ? '' : 's'}</h2>
          <p className="mt-1 font-serif text-[17px] text-zinc-200">{bytes(size)} · drop more, or{' '}
            <button type="button" className="text-accent hover:underline" onClick={() => files.current?.click()}>add more</button></p>
          <Thumbs picked={picked} onRemove={onRemove} />
          {/* The front door for a short (plan step 4): paste the reels it should
              feel like, and the video is made in their style as soon as the
              clips are read -- their pace, length and music feel, never their frames. */}
          <div className="mx-auto mt-5 max-w-[520px] text-left">
            <label className="font-serif text-[15px] text-zinc-200">Make it like a reel you love <span className="text-muted">(optional)</span></label>
            <textarea value={links} onChange={(e) => onLinks(e.target.value)} rows={hasLinks ? 3 : 1} spellCheck={false}
                      placeholder="Paste one to three links — TikTok, Reels, Shorts — or files on this Mac"
                      className="mt-1 w-full resize-none rounded-lg border border-line bg-ink px-3 py-2 font-mono text-[12px] text-zinc-200 outline-none placeholder:font-sans placeholder:text-zinc-500 focus:border-accent/60" />
            {hasLinks && <p className="mt-1 text-[11px] text-muted">Their pace, length and the feel of their music; nothing of their footage. Free music with a credit line.</p>}
          </div>
          <div className="mt-5 flex justify-center">
            <Btn onClick={onCreate} className={creating ? 'pointer-events-none opacity-60' : undefined}>
              {creating ? 'Creating…' : hasLinks ? 'Make a short like it' : 'Create'}
            </Btn>
          </div>
        </>
      )}
    </div>
    <p className="mt-5 text-center text-[12px] font-medium uppercase tracking-[0.16em] text-zinc-400">
      Runs on your Mac · No upload · Nothing generated
    </p>
    </>
  )
}

// A first frame for each picked file, straight from the file in the browser:
// nothing is read by the app until Create.
function Thumbs({ picked, onRemove }: { picked: Picked[]; onRemove: (i: number) => void }) {
  // One URL per file for as long as it's picked: removing one doesn't reload the rest.
  const made = useRef(new Map<Picked, string>())
  const urls = useMemo(() => picked.map((p) => {
    let u = made.current.get(p)
    if (!u) { u = URL.createObjectURL(p.file); made.current.set(p, u) }
    return u
  }), [picked])
  useEffect(() => {
    for (const [p, u] of made.current) if (!picked.includes(p)) { URL.revokeObjectURL(u); made.current.delete(p) }
  }, [picked])
  useEffect(() => () => { for (const u of made.current.values()) URL.revokeObjectURL(u); made.current.clear() }, [])
  return (
    <div className="mx-auto mt-4 flex max-h-[280px] max-w-3xl flex-wrap justify-center gap-1.5 overflow-y-auto p-1">
      {picked.map((p, i) => (
        <div key={`${p.relpath}|${p.file.size}`} className="group relative h-14 w-24 overflow-hidden rounded-md bg-zinc-900" title={p.file.name}>
          <video src={`${urls[i]}#t=0.3`} muted playsInline preload="metadata" className="size-full object-cover" />
          <span className="absolute inset-x-0 bottom-0 truncate bg-black/60 px-1 text-left text-[9px] text-zinc-300">{p.file.name}</span>
          <button type="button" aria-label={`Remove ${p.file.name}`} onClick={() => onRemove(i)}
                  className="absolute right-0.5 top-0.5 grid size-5 place-items-center rounded-full bg-black/75 text-[12px] leading-none text-zinc-100 opacity-0 hover:bg-black group-hover:opacity-100 focus:opacity-100">×</button>
        </div>
      ))}
    </div>
  )
}

function RenameProject({ p, onClose, onDone }: { p: ProjectMeta; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState(p.name)
  const [error, setError] = useState('')
  const submit = async () => {
    try { await api.renameProject(p.id, name.trim()); onDone() } catch (e) { setError((e as Error).message) }
  }
  return (
    <Dialog title="Rename" onClose={onClose} width={420}
            footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} disabled={!name.trim()}>Save</Button></>}>
      <form onSubmit={(e) => { e.preventDefault(); submit() }}>
        <Field label="Name"><input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={80} className={inputCls} /></Field>
        {error && <Notice tone="bad" className="mt-2">{error}</Notice>}
      </form>
    </Dialog>
  )
}

// Glad to see you, by the clock (sarah: "sound more enthusiastic"), then the
// question the page is for, in the landing page's italic turn.
function greeting(name: string, hour = new Date().getHours()): string {
  const part = hour >= 5 && hour < 12 ? 'Good morning' : hour >= 12 && hour < 18 ? 'Good afternoon' : 'Good evening'
  return name ? `${part}, ${name}.` : `${part}.`
}
