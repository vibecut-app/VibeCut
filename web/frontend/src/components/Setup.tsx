import { useEffect, useRef, useState } from 'react'
import { api, type AIEstimate, type AIState, type VibeJob } from '../api'
import { Button, Dialog, inputCls } from '../ui'
import { AISwitch } from './AISwitch'

// The two picks before anything is cut (plan of 2026-10-10, step 2): the
// frame the video is for, and the look of the whole thing. Everything else
// is read from the footage. Defaults come from the server; one button.
export type SetupData = {
  format: string; suggested?: string; portrait_share: number
  remembered?: { format?: string; look?: string; music?: string; vibe?: string }   // what was picked last time (defaults.py)
  music?: boolean
  // "Cut it like": your saved recipes (recipes.py), the library's vibes and your own learnt reels (vibes.py);
  // a recipe also brings the frame, look and music switch it was saved with
  vibes?: { id: string; name: string; line: string; kind: 'library' | 'reference' | 'recipe'
            dress?: { format: string | null; look: string | null; music: boolean } }[]
  vibe?: string | null
  formats: { key: string; label: string; seconds: number }[]
  look: string; looks: { id: string; name: string; line: string; font: string; palette: string[]; status: string }[]
  about: string
}

const GLYPH: Record<string, string> = { short: 'h-7 w-4', tall: 'h-7 w-4', wide: 'h-4 w-7' }

export function Setup({ data, busy, progress, onDone, onCancel, ai, estimate, onAI, onReload }: {
  data: SetupData | null
  ai?: AIState | null; estimate?: AIEstimate | null   // the AI switch, and what this edit would cost with it on
  onAI?: (on: boolean) => void
  busy: boolean
  onReload?: () => Promise<void>        // after a vibe is learnt in place, so it appears under Cut it like
  progress?: { line: string; done: number; total: number; elapsed: number } | null   // where the making is
  onDone: (format: string, look: string, music: boolean, vibe: string | null, aiCost: number | null) => void   // aiCost: the price shown, null = no AI
  onCancel: () => void
}) {
  const [format, setFormat] = useState<string | null>(null)
  const [look, setLook] = useState<string | null>(null)
  const [music, setMusic] = useState<boolean | null>(null)
  const [vibe, setVibe] = useState<string | null | undefined>(undefined)   // undefined = not touched
  const chosenVibe = vibe === undefined ? (data?.vibe ?? null) : vibe
  // learn a vibe from reels, right here (vibes.py as a job)
  const [learning, setLearning] = useState<{ open: boolean; niche: string; links: string; job: VibeJob | null; error: string | null }>({ open: false, niche: '', links: '', job: null, error: null })
  const learn = async () => {
    const links = learning.links.split(/\s+/).map((x) => x.trim()).filter(Boolean)
    setLearning((l) => ({ ...l, error: null }))
    try {
      let job = await api.vibeStart({ niche: learning.niche, links })
      setLearning((l) => ({ ...l, job }))
      while (job.stage === 'learning') {
        await new Promise((r) => window.setTimeout(r, 1500))
        job = await api.vibeStatus(job.id)
        setLearning((l) => ({ ...l, job }))
      }
      if (job.stage === 'error') throw new Error(job.error ?? 'Could not learn from those reels')
      await onReload?.()
      setVibe(job.vibe)
      setLearning({ open: false, niche: '', links: '', job: null, error: null })
    } catch (e) { setLearning((l) => ({ ...l, job: null, error: (e as Error).message })) }
  }
  const last = data?.remembered
  const first = useRef<HTMLButtonElement>(null)
  // a saved recipe brings its own frame, look and music switch; a pick made here still wins
  const recipe = data?.vibes?.find((v) => v.id === chosenVibe && v.kind === 'recipe')
  const fromRecipe = (k: 'format' | 'look') => {
    const v = recipe?.dress?.[k]
    return v && (k === 'format' ? data?.formats.some((f) => f.key === v) : data?.looks.some((l) => l.id === v)) ? v : null
  }
  const fmt = format ?? fromRecipe('format') ?? data?.format ?? 'tall'
  const lk = look ?? fromRecipe('look') ?? data?.look ?? 'cozy'
  const withMusic = music ?? recipe?.dress?.music ?? data?.music ?? true
  // rename or delete the picked recipe, right where it's picked
  const [editing, setEditing] = useState<{ mode: 'rename' | 'delete'; name: string; error: string | null } | null>(null)
  useEffect(() => { setEditing(null) }, [chosenVibe])
  const renameRecipe = async () => {
    if (!recipe || !editing?.name.trim()) return
    try { await api.renameRecipe(recipe.id, editing.name.trim()); await onReload?.(); setEditing(null) }
    catch (e) { setEditing((x) => x && { ...x, error: (e as Error).message }) }
  }
  const deleteRecipe = async () => {
    if (!recipe) return
    try { await api.deleteRecipe(recipe.id); setVibe(null); await onReload?.(); setEditing(null) }
    catch (e) { setEditing((x) => x && { ...x, error: (e as Error).message }) }
  }
  const asWhat = (k: 'format' | 'look', touched: boolean) =>
    touched ? null : fromRecipe(k) ? 'from your recipe' : last?.[k] ? 'as last time' : null
  useEffect(() => { first.current?.focus() }, [data])
  // a chosen vibe sets the cut itself, so the AI doesn't plan it (and nothing is spent)
  const aiOn = !!ai?.available && !!ai?.on && !chosenVibe
  const cost = aiOn && estimate?.on ? estimate.dollars : null
  const usd = (d: number) => d < 0.01 ? 'under 1¢' : `$${d.toFixed(2)}`
  const say = (s: number) => s < 60 ? `${s} s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

  return (
    <Dialog title="Two picks, then your video" sub={data ? `From the clips: ${data.about}. Length, pace and captions are read from the footage; change any of it in Frames.` : 'Reading your clips…'}
            onClose={onCancel} busy={busy} width={560}
            footer={<>
              {busy && progress && (
                <span className="mr-auto self-center text-[12px] text-muted">
                  {progress.line}{progress.total ? ` ${progress.done}/${progress.total}` : ''} · {Math.round(progress.elapsed)} s
                </span>
              )}
              <Button variant="ghost" onClick={onCancel} disabled={busy}>Not yet</Button>
              <Button variant="primary" onClick={() => onDone(fmt, lk, withMusic, chosenVibe, cost)} disabled={!data || busy || (aiOn && cost == null)}>
                {busy ? 'Making it…' : cost != null ? `Make my video · ${usd(cost)}` : 'Make my video'}
              </Button>
            </>}>
      <div className="space-y-4">
        {ai && onAI && (
          // what this edit will cost with AI, before anything is spent
          <div className="flex items-center gap-3 rounded-xl border border-line px-3 py-2.5">
            <AISwitch ai={ai} onToggle={onAI} busy={busy} />
            <p className="font-serif text-[15px] leading-snug text-zinc-200">
              {!ai.available ? 'No AI key on this Mac, so the usual rules make the edit.'
                : ai.on && chosenVibe ? 'Cutting it like a vibe follows that vibe, so AI doesn’t plan this one. Free.'
                : !aiOn ? 'Off: the usual rules make the edit, free.'
                : cost == null ? 'Working out what this edit costs…'
                : <>AI plans this edit into chapters, then looks over the finished cut and fixes it: about <b>{usd(cost)}</b> ({estimate!.moments} moments, {estimate!.model}). Nothing is spent until you press Make.</>}
            </p>
          </div>
        )}
        <div>
          <div className="mb-1.5 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Which frame?
            {asWhat('format', format !== null) && <span className="font-normal normal-case tracking-normal">{asWhat('format', false)}{data?.suggested && data.suggested !== fmt ? ` · the footage suggests ${data.suggested}` : ''}</span>}
          </div>
          <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Frame">
            {(data?.formats ?? []).map((f, i) => (
              <button key={f.key} type="button" role="radio" aria-checked={fmt === f.key} ref={i === 0 ? first : undefined}
                      onClick={() => setFormat(f.key)}
                      className={`flex flex-col items-center gap-2 rounded-xl border px-2 py-3 text-center ${fmt === f.key ? 'border-accent bg-raised text-zinc-100' : 'border-line text-zinc-400 hover:text-zinc-200'}`}>
                <span className={`block rounded-[3px] border-2 ${fmt === f.key ? 'border-accent' : 'border-zinc-500'} ${GLYPH[f.key] ?? 'h-5 w-5'}`} aria-hidden />
                <span className="font-serif text-[14px] leading-tight">{f.label.split(' · ')[0]}</span>
                <span className="text-[10px] leading-tight text-muted">{f.label.split(' · ')[1]} · about {say(f.seconds)}</span>
              </button>
            ))}
          </div>
          {data && data.portrait_share > 0 && data.portrait_share < 1 && (
            <p className="mt-1 text-[10px] text-muted">{Math.round(data.portrait_share * 100)}% of your footage is upright; the rest gets black bars in a vertical frame, and the other way round.</p>
          )}
        </div>
        <div>
          <div className="mb-1.5 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Which look?
            {asWhat('look', look !== null) && <span className="font-normal normal-case tracking-normal">{asWhat('look', false)}</span>}
          </div>
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Look">
            {(data?.looks ?? []).map((l) => (
              <button key={l.id} type="button" role="radio" aria-checked={lk === l.id} onClick={() => setLook(l.id)} title={l.line}
                      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] ${lk === l.id ? 'border-accent bg-raised text-zinc-100' : 'border-line text-zinc-400 hover:text-zinc-200'}`}>
                <span className="flex" aria-hidden>{l.palette.slice(0, 3).map((c) => <i key={c} className="block size-2.5 rounded-full ring-1 ring-black/40" style={{ background: c }} />)}</span>
                {l.name}
              </button>
            ))}
          </div>
          {data && <p className="mt-1 font-serif text-[13px] text-zinc-300">{data.looks.find((l) => l.id === lk)?.line}</p>}
          <p className="mt-0.5 text-[10px] text-muted">A look sets the words, the colour, how parts join and the music's feel. Change it later under Captions.</p>
        </div>
        {data && (data.vibes?.length ?? 0) > 0 && (
          <div>
            <div className="mb-1.5 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Cut it like
              {last?.vibe && vibe === undefined && <span className="font-normal normal-case tracking-normal">as last time</span>}
            </div>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Cut it like">
              <button type="button" role="radio" aria-checked={chosenVibe === null} onClick={() => setVibe(null)}
                      className={`rounded-full border px-2.5 py-1 text-[12px] ${chosenVibe === null ? 'border-accent bg-raised text-zinc-100' : 'border-line text-zinc-400 hover:text-zinc-200'}`}>
                This frame's own pace
              </button>
              {data.vibes!.map((v) => (
                <button key={v.id} type="button" role="radio" aria-checked={chosenVibe === v.id} onClick={() => setVibe(v.id)} title={v.line}
                        className={`rounded-full border px-2.5 py-1 text-[12px] ${chosenVibe === v.id ? 'border-accent bg-raised text-zinc-100' : 'border-line text-zinc-400 hover:text-zinc-200'}`}>
                  {v.kind === 'library' ? '✦ ' : v.kind === 'recipe' ? '♥ ' : ''}{v.name}
                </button>
              ))}
            </div>
            <p className="mt-1 font-serif text-[13px] text-zinc-300">{data.vibes!.find((v) => v.id === chosenVibe)?.line ?? 'Shot length, hook and words set by the frame you picked.'}</p>
            {recipe && (!editing ? (
              <p className="mt-1 flex gap-3 font-serif text-[13px]">
                <button type="button" className="text-accent hover:underline" onClick={() => setEditing({ mode: 'rename', name: recipe.name, error: null })}>Rename</button>
                <button type="button" className="text-rose-300 hover:underline" onClick={() => setEditing({ mode: 'delete', name: recipe.name, error: null })}>Delete</button>
              </p>
            ) : editing.mode === 'rename' ? (
              <div className="mt-1.5 flex items-center gap-2">
                <input autoFocus value={editing.name} maxLength={40} aria-label="Recipe name"
                       onChange={(e) => setEditing({ ...editing, name: e.target.value, error: null })}
                       onKeyDown={(e) => { if (e.key === 'Enter') renameRecipe(); if (e.key === 'Escape') setEditing(null) }}
                       className={`max-w-[16rem] py-1 font-serif text-[14px] ${inputCls}`} />
                <Button size="sm" variant="primary" onClick={renameRecipe} disabled={!editing.name.trim()}>Rename</Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
              </div>
            ) : (
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <span className="font-serif text-[14px] text-zinc-200">Delete “{recipe.name}”? It can't be brought back.</span>
                <Button size="sm" variant="danger" onClick={deleteRecipe}>Delete</Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Keep it</Button>
              </div>
            ))}
            {editing?.error && <p className="mt-1 font-serif text-[13px] text-rose-300">{editing.error}</p>}
          </div>
        )}
        {data && (
          <div>
            {!learning.open ? (
              <button type="button" className="text-[12px] text-accent hover:underline" onClick={() => setLearning((l) => ({ ...l, open: true }))}>
                {(data.vibes?.length ?? 0) ? '+ Learn a vibe from reels you love…' : 'Cut it like reels you love: learn a vibe from three or more…'}
              </button>
            ) : (
              <div className="rounded-lg border border-line p-2">
                <input value={learning.niche} onChange={(e) => setLearning((l) => ({ ...l, niche: e.target.value }))} placeholder="What they have in common, e.g. day in my life"
                       className="w-full rounded-md border border-line bg-panel px-2 py-1 text-[12px] text-zinc-100 outline-none focus:border-zinc-500" />
                <textarea value={learning.links} onChange={(e) => setLearning((l) => ({ ...l, links: e.target.value }))} rows={3} spellCheck={false}
                          placeholder={'Three or more links, one a line (TikTok, Reels, Shorts) — or files on this Mac'}
                          className="mt-1 w-full resize-none rounded-md border border-line bg-panel px-2 py-1 font-mono text-[11px] text-zinc-100 outline-none focus:border-zinc-500" />
                {learning.job ? (
                  <p className="mt-1 text-[11px] text-muted">Learning {learning.job.done}/{learning.job.total}… {learning.job.lines.at(-1) ?? ''} · {Math.round(learning.job.elapsed)} s</p>
                ) : (
                  <div className="mt-1.5 flex items-center gap-2">
                    <Button size="sm" variant="primary" onClick={learn} disabled={!learning.niche.trim() || learning.links.split(/\s+/).filter(Boolean).length < 3}>Learn it</Button>
                    <Button size="sm" variant="ghost" onClick={() => setLearning({ open: false, niche: '', links: '', job: null, error: null })}>Cancel</Button>
                    <span className="text-[10px] text-muted">Only numbers are kept from a reel; the first two minutes of each are read.</span>
                  </div>
                )}
                {learning.error && <p className="mt-1 text-[11px] text-rose-300">{learning.error}</p>}
              </div>
            )}
          </div>
        )}
        <label className="flex items-center gap-2 text-[12px] text-zinc-300">
          <input type="checkbox" checked={withMusic} onChange={(e) => setMusic(e.target.checked)} />
          Music under it{music === null && recipe?.dress ? <span className="text-muted"> · from your recipe</span>
            : last?.music && music === null ? <span className="text-muted"> · as last time</span> : null}
        </label>
      </div>
    </Dialog>
  )
}
