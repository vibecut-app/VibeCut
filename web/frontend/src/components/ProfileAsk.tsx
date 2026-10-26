import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api } from '../api'
import { ASKED_HERE, EMAIL, loadProfile, PACE_WORDS, saveProfile } from '../profile'
import type { CaptionTemplate, OverlayStyle, ProfileStart, ResourceFolder, ResourceKind, StartPicks } from '../types'
import { Button, cx, Dialog, inputCls } from '../ui'
import { Icon } from './icons'
import { LogIn } from './Resources'
import { CaptionSample, JoinSample, Tile } from './StyleBars'
import { TEMPLATE_NAMES, TRANSITION_NAMES, useLoop } from '../styleNames'

// Your profile, asked once after an export (sarah, 2026-10-14: "after
// exporting for the first time, ask to create user profile using email and
// remember the user's preference"; back 2026-10-19). The email is the only
// thing typed; everything else is a tap on a picture, already on what the
// video just exported used. Saved, it's where every next video starts
// (pace, captions, the transition at every cut); Skip and it isn't asked
// again. My resources sits beside it: one tap keeps this video's looks.
// Logged out, it asks for an account instead, the way My resources does.

export type Picks = {
  makes: 'vlog' | 'lesson' | null
  pace: 'fast' | 'balanced' | 'calm' | null
  transition: string | null
  captions: boolean
  template: CaptionTemplate | null
}

type Pick = { key: string; label: string; art: ReactNode }
const MAKES: Pick[] = [
  { key: 'vlog', label: 'Vlogs', art: <Strip /> },
  { key: 'lesson', label: 'Lessons', art: <Board /> },
]
const PACES: Pick[] = [
  { key: 'fast', label: 'Quick', art: <Beats n={9} /> },
  { key: 'balanced', label: 'Steady', art: <Beats n={5} /> },
  { key: 'calm', label: 'Calm', art: <Beats n={3} /> },
]
// what a caption tile is drawn with when there's no video behind it (the profile page)
const PLAIN_STYLE: OverlayStyle = { font: 'Clean', color: '#ffffff', accent: '#b9d9eb', captions: 'bottom', backing: 'shadow' }
const KEEP: { kind: ResourceKind; label: string }[] = [
  { kind: 'caption', label: 'Caption look' }, { kind: 'animation', label: 'Animation' },
  { kind: 'transition', label: 'Transition' }, { kind: 'effect', label: 'Effect' }, { kind: 'song', label: 'Song' },
]

/** The four questions, as tiles. The popup and the profile page both use it. */
export function StartChoices({ picks, onPick, style = PLAIN_STYLE, from = null, to = null }: {
  picks: Picks
  onPick: (patch: Partial<Picks>) => void
  style?: OverlayStyle
  from?: string | null
  to?: string | null
}) {
  const m = useLoop(1.8)
  const bg = from ? { backgroundImage: `url(${from})`, backgroundSize: 'cover', backgroundPosition: 'center' }
    : { background: 'linear-gradient(155deg,#4a4d55 0%,#2b3038 55%,#15181d 100%)' }
  const plain = { ...style, outline: null, shadow: null, backdrop: null, thick: null, enter: null }
  return (
    <div className="space-y-4">
      <Row title="What do you make?" picks={MAKES} value={picks.makes} onPick={(k) => onPick({ makes: k as Picks['makes'] })} />
      <Row title="How fast do you like the cuts?" picks={PACES} value={picks.pace} onPick={(k) => onPick({ pace: k as Picks['pace'] })} />
      <TileRow title="How should one shot flow into the next?">
        {Object.entries(TRANSITION_NAMES).map(([id, name]) => (
          <Tile key={id} on={(picks.transition ?? 'cut') === id} label={name} onClick={() => onPick({ transition: id })}>
            <JoinSample kind={id} from={from} to={to} m={m} />
          </Tile>
        ))}
      </TileRow>
      <TileRow title="Your captions">
        <Tile on={picks.captions && !picks.template} label="Soft" onClick={() => onPick({ captions: true, template: null })}>
          <span className="absolute inset-0" style={bg} />
          <CaptionSample style={{ ...plain, template: null }} text="Aa" t={2} />
        </Tile>
        {(Object.keys(TEMPLATE_NAMES) as CaptionTemplate[]).map((id) => (
          <Tile key={id} on={picks.captions && picks.template === id} label={TEMPLATE_NAMES[id]}
                onClick={() => onPick({ captions: true, template: id })}>
            <span className="absolute inset-0" style={bg} />
            <CaptionSample style={{ ...plain, template: id }} text="Aa" t={2} />
          </Tile>
        ))}
        <Tile on={!picks.captions} label="No captions" onClick={() => onPick({ captions: false })}>
          <span className="absolute inset-0" style={bg} />
        </Tile>
      </TileRow>
    </div>
  )
}

export function ProfileAsk({ start, current, style, from, to, folder, keepWhy, onKeep, onDone }: {
  start: ProfileStart
  /** what the video just exported used, so most people only type their email */
  current: Picks
  style: OverlayStyle
  from: string | null
  to: string | null
  folder: ResourceFolder | null
  /** null = this video has one to keep (App's saveWhy) */
  keepWhy: Record<ResourceKind, string | null>
  onKeep: (kind: ResourceKind) => Promise<boolean>
  onDone: () => void
}) {
  if (!start.signed_in) return <AskAccount folder={folder} onDone={onDone} />
  return <AskProfile current={current} style={style} from={from} to={to} keepWhy={keepWhy} onKeep={onKeep} onDone={onDone} />
}

function AskProfile({ current, style, from, to, keepWhy, onKeep, onDone }: {
  current: Picks; style: OverlayStyle; from: string | null; to: string | null
  keepWhy: Record<ResourceKind, string | null>; onKeep: (kind: ResourceKind) => Promise<boolean>; onDone: () => void
}) {
  const [mine] = useState(() => { try { return loadProfile(window.localStorage).profile } catch { return null } })
  const [name, setName] = useState(mine?.name ?? '')
  const [email, setEmail] = useState(mine?.email ?? '')
  const [picks, setPicks] = useState<Picks>(current)
  const [kept, setKept] = useState<Partial<Record<ResourceKind, 'saving' | 'saved'>>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const field = useRef<HTMLInputElement>(null)
  useEffect(() => { field.current?.focus() }, [])
  const ok = EMAIL.test(email.trim())
  const keepable = KEEP.filter((k) => !keepWhy[k.kind])

  const skip = () => { if (!busy) api.profileSkip().catch(() => {}).finally(onDone) }
  const save = async () => {
    if (!ok) { setError('That doesn’t look like an email address yet.'); return }
    setBusy(true); setError(null)
    try {
      const sent: StartPicks = { ...picks }
      await api.profileStartSave(sent)
      // the name and email belong to the profile page's profile, in this browser and beside the defaults
      if (mine) {
        try {
          const next = saveProfile(window.localStorage, { ...mine, name: name.trim() || mine.name, email: email.trim(),
                                                         pace: picks.pace ? PACE_WORDS[picks.pace] : mine.pace })
          api.profilePut(next as unknown as Record<string, unknown>).catch(() => {})
        } catch { /* storage blocked: the picks are saved on the server all the same */ }
      }
      onDone()
    } catch (e) { setError((e as Error).message); setBusy(false) }
  }
  const keep = async (kind: ResourceKind) => {
    if (kept[kind]) return
    setKept((k) => ({ ...k, [kind]: 'saving' }))
    const done = await onKeep(kind)
    setKept((k) => ({ ...k, [kind]: done ? 'saved' : undefined }))
  }

  return (
    <Dialog title="Your video is done! 🎉" width={760} busy={busy} onClose={skip} id="profile-title"
            sub={<span className="font-serif text-[16px] text-zinc-300">Make your profile, and your next video starts the way you like it.</span>}
            footer={<>
              <Button variant="ghost" onClick={skip} disabled={busy}>Not now</Button>
              <Button variant="primary" onClick={save} disabled={busy || !ok}>{busy ? 'Saving…' : 'Save my profile'}</Button>
            </>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save() }}>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block font-serif text-[17px] text-zinc-100">Your email</span>
            <input ref={field} type="email" autoComplete="email" value={email} placeholder="you@example.com" maxLength={254}
                   onChange={(e) => { setEmail(e.target.value); setError(null) }} className={cx(inputCls, 'text-[15px]')} />
          </label>
          <label className="block">
            <span className="mb-1.5 block font-serif text-[17px] text-zinc-100">Your name</span>
            <input type="text" autoComplete="given-name" value={name} placeholder="What should we call you?" maxLength={80}
                   onChange={(e) => setName(e.target.value)} className={cx(inputCls, 'text-[15px]')} />
          </label>
        </div>
        <p className="font-serif text-[15px] text-zinc-300">Your email names your profile. Nothing is sent to it.</p>
        {error && <p className="font-serif text-[15px] text-rose-300" role="alert">{error}</p>}
        <StartChoices picks={picks} onPick={(p) => setPicks((x) => ({ ...x, ...p }))} style={style} from={from} to={to} />
        {keepable.length > 0 && (
          <div>
            <div className="mb-1.5 font-serif text-[17px] text-zinc-100">Keep this video’s looks in My resources</div>
            <div className="flex flex-wrap gap-2">
              {keepable.map((k) => (
                <button key={k.kind} type="button" onClick={() => keep(k.kind)} disabled={!!kept[k.kind]}
                        className={cx('flex items-center gap-1.5 rounded-xl border px-3 py-1.5 font-serif text-[15px]',
                          kept[k.kind] === 'saved' ? 'border-emerald-400/50 bg-emerald-400/10 text-emerald-200'
                            : 'border-accent/60 bg-accent/6 text-accent hover:bg-accent/12')}>
                  <Icon name={kept[k.kind] === 'saved' ? 'check' : 'plus'} size={16} />
                  {kept[k.kind] === 'saved' ? `${k.label} saved` : k.label}
                </button>
              ))}
            </div>
          </div>
        )}
        <p className="font-serif text-[15px] text-zinc-300">
          We picked what this video used. Change anything later in your profile, or in the editor: your profile keeps up.
        </p>
      </form>
    </Dialog>
  )
}

// Logged out (a shared link): there's nowhere to keep a profile but an account.

function AskAccount({ folder, onDone }: { folder: ResourceFolder | null; onDone: () => void }) {
  const close = () => { try { window.localStorage.setItem(ASKED_HERE, '1') } catch { /* asked again next time */ } onDone() }
  return (
    <Dialog title="Your video is done! 🎉" width={480} onClose={close} id="profile-title"
            footer={<Button variant="ghost" onClick={close}>Not now</Button>}>
      <LogIn login={folder?.signin_url ?? null} signup={folder?.signup_url ?? folder?.signin_url ?? null}
             title="Log in to keep your profile"
             text="Your profile starts every next video the way you like it: your pace, your transitions, your captions and My resources." />
    </Dialog>
  )
}

function TileRow({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 font-serif text-[17px] text-zinc-100">{title}</div>
      <div className="flex items-start gap-3 overflow-x-auto pb-1">{children}</div>
    </div>
  )
}

function Row({ title, picks, value, onPick }: { title: string; picks: Pick[]; value: string | null; onPick: (k: string) => void }) {
  return (
    <div>
      <div className="mb-1.5 font-serif text-[17px] text-zinc-100">{title}</div>
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={title}>
        {picks.map((p) => (
          <button key={p.key} type="button" role="radio" aria-checked={value === p.key} onClick={() => onPick(p.key)}
                  className={cx('flex w-[96px] flex-col items-center gap-1 rounded-xl border p-1.5 text-center transition-colors',
                    value === p.key ? 'border-accent bg-raised text-zinc-100 ring-1 ring-accent' : 'border-line text-zinc-300 hover:bg-raised')}>
            <span className="grid h-10 w-full place-items-center overflow-hidden rounded-lg" aria-hidden>{p.art}</span>
            <span className="font-serif text-[15px] leading-tight">{p.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ---- the little pictures ----------------------------------------------------

const SKY = ['#f4a261', '#8ecae6', '#90be6d', '#e76f51']

function Strip() {
  return <span className="flex gap-1">{SKY.slice(0, 3).map((c) => <i key={c} className="block h-8 w-5 rounded-[4px]" style={{ background: `linear-gradient(${c}, #2a3440)` }} />)}</span>
}

function Board() {
  return (
    <span className="relative block h-9 w-16 rounded-[4px] bg-[#2f4f3f] p-1.5">
      {[40, 32, 24].map((w) => <i key={w} className="mb-1 block h-[3px] rounded bg-white/80" style={{ width: w }} />)}
      <i className="absolute -right-1 bottom-0 block size-3 rounded-full bg-[#f4a261]" />
    </span>
  )
}

function Beats({ n }: { n: number }) {
  return (
    <span className="flex h-7 w-[72px] gap-[2px]">
      {Array.from({ length: n }, (_, i) => <i key={i} className="block h-full flex-1 rounded-[3px]" style={{ background: SKY[i % SKY.length] }} />)}
    </span>
  )
}
