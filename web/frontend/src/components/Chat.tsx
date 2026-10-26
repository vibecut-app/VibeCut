import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type ChatEstimate, type ChatProvider, type CheckEstimate } from '../api'
import { cents, centsRange } from '../format'
import { locate, type SeqItem } from '../sequence'
import { phStore, useStore } from '../transport'
import type { PrefSuggestion, DiffLine, Msg, PrefCandidate, Preferences, Review, Turn } from '../types'
import { Remember, Rules, type ClassifyReq } from './Remember'

const EXAMPLE = 'three days in Tokyo, lean into the food'
// Things the chat can do (board ops), for the whole video or for the shot
// it's about. A tap puts one in the box, so its cost is on Send first.
const IDEAS = ['Make it shorter', 'Open on the best moment', 'Less of my face', 'Make the opening punchier', 'Make the captions easier to read']
const SHOT_IDEAS = ['Cut this shot', 'Make this shot shorter', 'Swap it for a better one', 'Open the video with it']

export type ChatItem = { type: 'local'; msg: Msg } | { type: 'turn'; turn: Turn }
// What a message goes with: the moment it's about (edit seconds) and the cost the box showed.
export type SendExtra = { t: number | null; ai_ok: number | null }

const MARK: Record<DiffLine['kind'], { sym: string; cls: string }> = {
  removed: { sym: '−', cls: 'text-rose-300 bg-rose-400/10' },
  added: { sym: '+', cls: 'text-emerald-300 bg-emerald-400/10' },
  swapped: { sym: '⇄', cls: 'text-emerald-300 bg-emerald-400/10' },
  moved: { sym: '↕', cls: 'text-amber-200 bg-amber-300/10' },
  trimmed: { sym: '⟷', cls: 'text-sky-300 bg-sky-400/10' },
  retitled: { sym: 'Aa', cls: 'text-violet-300 bg-violet-400/10' },
  replaced: { sym: '▸', cls: 'text-zinc-300 bg-zinc-700/40' },
  style: { sym: '✦', cls: 'text-violet-300 bg-violet-400/10' },
  sound: { sym: '♪', cls: 'text-sky-300 bg-sky-400/10' },
  none: { sym: '·', cls: 'text-zinc-500 bg-zinc-800/40' },
}

const clock = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`

// The shot a message would be about: the clicked one, else the one under the
// paused playhead (pausing means something there should change; sarah,
// 2026-10-05). Read in its own component, so the playhead moving re-renders
// only this chip, and the chat hears of it only when the shot changes.
function useAbout(timeline: SeqItem[], paused: boolean, selected: SeqItem | null) {
  const t = useStore(phStore)
  const here = paused ? timeline[locate(timeline, t)] : undefined
  const it = selected ?? (here && here.kind === 'shot' ? here : null)
  return { it, t }
}

function About({ timeline, paused, selected, whole, onWhole, onKey }: {
  timeline: SeqItem[]; paused: boolean; selected: SeqItem | null
  whole: boolean; onWhole: (w: boolean) => void; onKey: (key: string | null) => void
}) {
  const { it, t } = useAbout(timeline, paused, selected)
  const key = it?.key ?? null
  useEffect(() => { onKey(key) }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!it) return null
  const at = t >= it.seq_start && t < it.seq_end ? t : it.seq_start
  const pill = (on: boolean) => `rounded-full px-3 py-1 font-serif text-[15px] ${on
    ? 'bg-accent text-accent-ink' : 'text-zinc-300 hover:bg-raised'}`
  return (
    <div className="flex flex-wrap items-center gap-1.5 px-1 pb-2">
      <span className="font-serif text-[15px] text-zinc-300">About</span>
      <button type="button" aria-pressed={!whole} onClick={() => onWhole(false)} className={pill(!whole)}>
        {it.n ? `Shot ${it.n}` : 'This shot'} · {clock(at)}
      </button>
      <button type="button" aria-pressed={whole} onClick={() => onWhole(true)} className={pill(whole)}>
        Whole video
      </button>
    </div>
  )
}

// The AI Edit panel (History while no AI answers). Who answers is `who`:
// OpenAI on the course key while the AI switch is on (sarah, 2026-10-18),
// else Claude if its key is set. One box, like other editors' assistants:
// it's about the clicked or paused shot unless "Whole video" is picked;
// Send shows what the message costs before it goes; while it thinks, Stop;
// each answer shows what it cost and has its Undo; the header keeps what AI
// has cost on this video. Check my edit: the AI looks over every shot of the
// cut at once and fixes what's clearly wrong, priced on the button first.
export function Chat({ items, pending, pendingLine, onSend, onStop, onCheck, onToggle, disabled, who, turnsKey, spent, aiSwitch, aiKey, hasBoard,
  timeline, paused, selected, prefs, onClassify, onRule, onSuggest, review }: {
  items: ChatItem[]
  pending: string | null
  pendingLine?: string            // what it's doing while it thinks
  onSend: (text: string, extra: SendExtra) => void
  onStop?: () => void
  onCheck?: (aiOk: number) => void   // the price the button showed
  onToggle: (turn: number) => void
  disabled: boolean
  who: ChatProvider
  turnsKey: string                // changes with the edit: the prompt (and its price) moved
  spent?: number                  // dollars AI has cost on this video
  aiSwitch?: ReactNode
  aiKey?: boolean                 // the course key is on this Mac (the switch can turn AI on)
  hasBoard: boolean
  timeline?: SeqItem[]
  paused?: boolean
  selected?: SeqItem | null
  prefs: Preferences | null
  onClassify: (r: ClassifyReq) => Promise<void>
  onRule: (id: string, action: 'forget' | 'narrow') => void
  onSuggest?: (r: { id: string; klass: 'long_term' | 'project' | 'rejected'; rule?: string; scope?: string; counter?: string }) => Promise<void>
  review?: { turn: number; items: Review[] } | null
}) {
  const candidate = new Map((prefs?.candidates ?? []).map((c) => [c.turn, c]))
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [items.length, pending])

  // what it's about: a shot (by key) unless the creator picked the whole video;
  // a new shot under the playhead asks about that shot again
  const [shotKey, setShotKey] = useState<string | null>(null)
  const [whole, setWhole] = useState(false)
  useEffect(() => { setWhole(false) }, [shotKey])
  const target = hasBoard && who && shotKey && !whole ? shotKey : null
  const aboutT = () => {
    if (!target || !timeline) return null
    const it = timeline.find((x) => x.key === target)
    if (!it) return null
    const t = phStore.get()
    return t >= it.seq_start && t < it.seq_end ? t : it.seq_start + 0.05
  }

  // What one message costs, read before anything is sent (free): again when
  // who answers, the edit or the shot it's about changes.
  const [cost, setCost] = useState<ChatEstimate | null>(null)
  const [costErr, setCostErr] = useState(false)
  const [ask, setAsk] = useState(0)
  useEffect(() => {
    setCost(null)
    setCostErr(false)
    if (!who) return
    let live = true
    api.chatEstimate(aboutT()).then((e) => live && setCost(e), () => live && setCostErr(true))
    return () => { live = false }
  }, [who, turnsKey, target, ask]) // eslint-disable-line react-hooks/exhaustive-deps

  // What one look over the whole cut costs (free to ask), again when the edit changes.
  const [checkCost, setCheckCost] = useState<CheckEstimate | null>(null)
  useEffect(() => {
    setCheckCost(null)
    if (who !== 'openai' || !onCheck) return
    let live = true
    api.checkEstimate().then((e) => live && setCheckCost(e), () => {})
    return () => { live = false }
  }, [who, turnsKey, !!onCheck]) // eslint-disable-line react-hooks/exhaustive-deps

  // What a message of n characters costs: the estimate counts a short one,
  // each character past that adds its share (both ends of the range).
  const usdFor = (n: number): [number, number] | null => {
    if (!cost?.on) return null
    const more = Math.max(0, n - (cost.base_chars ?? 0)) * (cost.per_char ?? 0)
    return [cost.usd[0] + more, cost.usd[1] + more]
  }
  // On the course key a message needs its cost shown first; with no AI an
  // edit can't be typed (the first description still works, by keywords).
  const priced = who !== 'openai' || !!cost?.on
  const locked = !who && hasBoard
  const send = (t = text) => {
    t = t.trim()
    if (!t || disabled || !priced || locked) return
    const usd = usdFor(t.length)
    // the cost goes with the message only when the estimate was the course key's
    onSend(t, { t: aboutT(), ai_ok: cost?.provider === 'openai' && usd ? usd[1] : null })
    setText('')
  }
  // a description that built the edit isn't a conversation yet
  const talked = items.some((i) => i.type === 'turn' && i.turn.kind === 'chat' && !i.turn.direction)
  const usdNow = usdFor(text.trim().length)
  const price = usdNow ? centsRange(usdNow) : null
  const priceOf = (t: string) => { const u = usdFor(t.trim().length); return u ? centsRange(u) : null }
  const label = !who ? 'Send' : price ? `Send · ${price}`
    : who === 'openai' ? (cost && !cost.on ? 'AI is off' : 'Working out the cost…') : 'Send'
  const lastQuestion = [...items].reverse().find((i) => i.type === 'turn')
  const openChoices = lastQuestion?.type === 'turn' && lastQuestion.turn.question && !lastQuestion.turn.undone
    ? lastQuestion.turn.id : null
  const ideas = target ? SHOT_IDEAS : IDEAS
  const stoppable = !!pending && !!who && !!onStop

  return (
    <aside className="flex min-h-0 flex-col border-r border-line bg-panel">
      <header className="flex h-14 shrink-0 items-center gap-2 px-4">
        <span className="font-serif text-[19px] text-zinc-100">{who ? 'AI Edit' : 'History'}</span>
        <div className="flex-1" />
        {!!spent && <span className="font-serif text-[15px] text-zinc-300" title="What AI has cost on this video so far">{cents(spent)} spent</span>}
        {aiKey && aiSwitch}
      </header>
      {prefs && <Rules rules={prefs.rules} onRule={onRule} />}
      {prefs?.suggestions?.length ? <Suggested items={prefs.suggestions} onDone={onSuggest} /> : null}

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {hasBoard && (
          <p className="font-serif text-[16px] leading-snug text-zinc-200">
            {who ? 'Your edit is ready. Tell me what to change, and every change has its Undo.'
              : aiKey ? 'Turn AI on to edit by chat. Each message shows what it costs before it’s sent. Every change you make is listed here with its Undo.'
                : 'There’s no AI key on this Mac, so editing by chat is off. Every change you make is still listed here with its Undo.'}
          </p>
        )}
        {items.filter((it) => !(it.type === 'local' && it.msg.id === 'hello')).map((it) => it.type === 'local'
          ? <Local key={it.msg.id} m={it.msg} price={it.msg.retry ? priceOf(it.msg.retry) : null}
                   onRetry={it.msg.retry && who ? () => send(it.msg.retry ?? '') : undefined} />
          : <TurnView key={`t${it.turn.id}`} t={it.turn} onToggle={onToggle}
                      candidate={candidate.get(it.turn.id)} onClassify={onClassify}
                      review={review && review.turn === it.turn.id ? review.items : undefined}
                      onChoice={openChoices === it.turn.id ? (c) => send(c) : undefined} />)}
        {pending && (
          <>
            <div className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-md bg-accent px-3 py-2 font-serif text-[16px] leading-snug text-accent-ink">{pending}</div>
            </div>
            <div className="font-serif text-[15px] text-zinc-300"><span className="mr-2 inline-block size-2 animate-pulse rounded-full bg-accent align-middle" />{pendingLine ?? 'Working out the edit…'}</div>
          </>
        )}
        <div ref={end} />
      </div>

      <div className="shrink-0 border-t border-line p-3">
        {/* things it can do, until the first message: a tap fills the box, so the price is on Send first */}
        {hasBoard && who && !talked && !pending && !text.trim() && (
          <div className="flex flex-wrap gap-1.5 px-1 pb-2.5">
            {ideas.map((c) => (
              <button key={c} type="button" onClick={() => setText(c)}
                      className="rounded-full border border-line px-3 py-1 font-serif text-[15px] text-zinc-200 hover:bg-raised">
                {c}
              </button>
            ))}
          </div>
        )}
        {hasBoard && who === 'openai' && onCheck && checkCost?.on && !pending && (
          <div className="px-1 pb-2.5">
            <button type="button" onClick={() => onCheck(checkCost.dollars)} disabled={disabled}
                    title="The AI looks over every shot of your cut at once and fixes repeats, slow parts, the opening and the ending. One Undo takes it all back."
                    className="rounded-full border border-accent/60 px-3 py-1 font-serif text-[15px] text-accent hover:bg-accent hover:text-accent-ink disabled:opacity-30">
              ✦ Check my whole edit · {cents(checkCost.dollars)}
            </button>
          </div>
        )}
        {hasBoard && who && timeline && (
          <About timeline={timeline} paused={!!paused} selected={selected ?? null}
                 whole={whole} onWhole={setWhole} onKey={setShotKey} />
        )}
        <div className="rounded-xl border border-line bg-raised focus-within:border-zinc-500">
          <textarea
            rows={2}
            value={text}
            disabled={locked}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
            }}
            placeholder={locked ? (aiKey ? 'Turn AI on to edit by chat' : 'Editing by chat needs an AI key')
              : target ? 'What should change in this shot?'
                : hasBoard ? 'What should change? “the opening is too slow”, “cut the market”, “end on the sunset”'
                  : `What's this video? e.g. “${EXAMPLE}”`}
            className="block w-full resize-none bg-transparent px-3 pt-2.5 font-serif text-[15px] text-zinc-100 outline-none placeholder:text-zinc-500 disabled:opacity-50"
          />
          <div className="flex items-center justify-between gap-2 px-2 pb-2">
            {!hasBoard ? (
              <button type="button" onClick={() => setText(EXAMPLE)}
                      className="rounded-md px-1.5 py-1 font-serif text-[15px] text-zinc-300 hover:text-zinc-100">
                Try an example
              </button>
            ) : costErr && who === 'openai' ? (
              <button type="button" onClick={() => setAsk((n) => n + 1)}
                      className="rounded-md px-1.5 py-1 font-serif text-[15px] text-accent hover:underline">
                Couldn’t price it · Price it again
              </button>
            ) : <span />}
            {stoppable ? (
              <button type="button" onClick={onStop}
                      title="Stop: the answer changes nothing when it comes (what it cost is still counted)"
                      className="rounded-lg border border-line px-3 py-1 font-serif text-[15px] text-zinc-100 hover:bg-raised">
                Stop
              </button>
            ) : (
              <button
                type="button"
                onClick={() => send()}
                disabled={disabled || !text.trim() || !priced || locked}
                title={who ? 'What this message will cost, before it’s sent' : undefined}
                className="rounded-lg bg-accent px-3 py-1 font-serif text-[15px] text-accent-ink disabled:opacity-30"
              >
                {label}
              </button>
            )}
          </div>
        </div>
      </div>
    </aside>
  )
}

function Local({ m, price, onRetry }: { m: Msg; price: string | null; onRetry?: () => void }) {
  if (m.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-accent px-3 py-2 font-serif text-[16px] leading-snug text-accent-ink">{m.text}</div>
      </div>
    )
  }
  return (
    <div className="max-w-[95%] whitespace-pre-line font-serif text-[16px] leading-relaxed text-zinc-200">
      {m.busy && <span className="mr-2 inline-block size-2 animate-pulse rounded-full bg-accent align-middle" />}
      {m.text}
      {onRetry && (
        <div className="mt-1.5">
          <button type="button" onClick={onRetry}
                  className="rounded-full border border-accent/60 px-3 py-1 font-serif text-[15px] text-accent hover:bg-accent hover:text-accent-ink">
            Try again{price ? ` · ${price}` : ''}
          </button>
        </div>
      )}
    </div>
  )
}

function TurnView({ t, onToggle, onChoice, candidate, onClassify, review }: {
  t: Turn; onToggle: (id: number) => void; onChoice?: (c: string) => void
  candidate?: PrefCandidate; onClassify: (r: ClassifyReq) => Promise<void>
  review?: Review[]
}) {
  const remember = candidate && !t.undone && t.kind !== 'check' && <Remember c={candidate} onClassify={onClassify} />
  const faded = t.undone ? 'opacity-40' : ''
  const paid = t.cost != null && t.cost > 0 && (
    <span className="shrink-0 font-serif text-[15px] text-zinc-300" title="What the AI's answer cost">{cents(t.cost)}</span>
  )
  const undo = t.has_ops && (
    <button type="button" onClick={() => onToggle(t.id)}
            className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${t.undone
              ? 'text-accent hover:bg-raised' : 'text-muted hover:bg-raised hover:text-zinc-200'}`}
            title={t.undone ? 'Re-apply this turn' : 'Undo this turn — later turns stay'}>
      {t.undone ? 'Redo' : 'Undo'}
    </button>
  )

  return (
    <div className="space-y-1.5">
      {t.kind === 'direct' ? (
        // Direct edits (Apply, timeline drag/delete) are one compact row.
        <div className="flex items-center gap-2 text-[11px]">
          <span className={`h-px w-3 bg-line ${faded}`} />
          <span className={`min-w-0 flex-1 truncate text-muted ${t.undone ? 'line-through opacity-50' : ''}`}
                title={t.lines.map((l) => l.text).join(' · ')}>
            {t.text}{t.lines[0] && t.lines[0].kind !== 'replaced' && t.lines[0].kind !== 'none'
              ? <span className="text-zinc-500"> — {t.lines.map((l) => l.text).join(' · ')}</span> : null}
          </span>
          {t.skipped.length > 0 && <span className="text-amber-200/80" title={t.skipped.join('\n')}>skipped</span>}
          {undo}
        </div>
      ) : t.kind === 'check' ? null : (
        <div className="flex justify-end">
          <div className={`max-w-[85%] rounded-2xl rounded-br-md bg-accent px-3 py-2 font-serif text-[16px] leading-snug text-accent-ink ${faded}`}>{t.text}</div>
        </div>
      )}
      {t.kind === 'direct' && remember ? <div className="flex flex-wrap justify-end pl-5">{remember}</div> : null}
      {review && review.length > 0 && !t.undone && <ReviewLines items={review} />}

      {(t.kind === 'chat' || t.kind === 'check') && (t.reply || t.question || t.lines.length > 0 || t.skipped.length > 0 || t.direction) && (
        <div className={`rounded-lg border border-line bg-raised/60 px-2.5 py-2 ${t.undone ? 'opacity-50' : ''}`}>
          <div className="flex items-start gap-2">
            <div className={`min-w-0 flex-1 font-serif text-[16px] leading-snug ${t.undone ? 'line-through decoration-zinc-600' : ''}`}>
              {t.question ? <span className="text-zinc-100">{t.question}</span>
                : t.reply ? <span className="text-zinc-300">{t.reply}</span>
                  : t.direction ? <span className="text-zinc-300">Made your edit from your clips{t.direction.themes?.length ? `, leaning into ${t.direction.themes.join(' + ')}` : ''}.</span>
                    : null}
            </div>
            {paid}
            {undo}
          </div>

          {t.kind === 'check' && !!t.sheets?.length && !t.undone && (
            // what the AI looked at: one still from every shot, numbered as the timeline numbers them
            <div className="mt-2">
              <div className="mb-1 font-serif text-[15px] text-zinc-300">What it looked at</div>
              <div className="flex flex-wrap gap-1.5">
                {t.sheets.map((n) => (
                  <a key={n} href={`/api/check/sheet/${n}`} target="_blank" rel="noreferrer" title="Open it full size">
                    <img src={`/api/check/sheet/${n}`} alt="Every shot of the cut, numbered" className="h-16 rounded border border-line object-cover" />
                  </a>
                ))}
              </div>
            </div>
          )}

          {t.question && t.choices.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {t.choices.map((c) => (
                <button key={c} type="button" disabled={!onChoice} onClick={() => onChoice?.(c)}
                        className="rounded-full border border-accent/50 px-2.5 py-1 text-[12px] text-accent hover:bg-accent hover:text-accent-ink disabled:border-line disabled:text-muted disabled:hover:bg-transparent">
                  {c}
                </button>
              ))}
            </div>
          )}

          {t.lines.filter((l) => l.kind !== 'none' || !t.direction).length > 0 && (
            <ul className={`mt-2 space-y-1 ${t.undone ? 'line-through decoration-zinc-600' : ''}`}>
              {t.lines.filter((l) => l.kind !== 'none' || !t.direction).map((l, i) => (
                <li key={i} className="flex items-center gap-2 text-[12px]">
                  <span className={`grid h-5 min-w-5 place-items-center rounded px-1 text-[11px] font-semibold ${(MARK[l.kind] ?? MARK.none).cls}`}>{(MARK[l.kind] ?? MARK.none).sym}</span>
                  <span className="min-w-0 flex-1 text-zinc-300">{l.text}</span>
                  {l.thumb && <img src={l.thumb} className="h-5 w-9 shrink-0 rounded-sm object-cover" />}
                </li>
              ))}
            </ul>
          )}
          {t.skipped.map((s) => (
            <p key={s} className="mt-1.5 text-[11px] text-amber-200/80">Skipped: {s}</p>
          ))}
          {remember && <div className="mt-1.5 flex flex-wrap justify-end">{remember}</div>}
        </div>
      )}
    </div>
  )
}

// A second look at the latest turn: the cuts it made rougher, or smoothed.
// Report only -- nothing is changed; the numbers are on the cut in Story.
function ReviewLines({ items }: { items: Review[] }) {
  return (
    <ul className="space-y-0.5 pl-5 text-[11px]">
      {items.map((r, i) => (
        <li key={i} className={r.kind === 'better' ? 'text-emerald-300/80'
          : r.verdict === 'bad' ? 'text-rose-300/90' : 'text-amber-200/80'}>
          {r.kind === 'better' ? `✓ ${r.text}` : `! A cut at ${Math.floor((r.at ?? 0) / 60)}:${String(Math.floor((r.at ?? 0) % 60)).padStart(2, '0')} got rougher: ${r.text.charAt(0).toLowerCase()}${r.text.slice(1)}`}
        </li>
      ))}
    </ul>
  )
}


// What you undid or refused, offered once as a rule (preferences.suggestions).
// Nothing is applied from here by itself: every video needs when / when not.
function Suggested({ items, onDone }: { items: PrefSuggestion[]; onDone?: (r: { id: string; klass: 'long_term' | 'project' | 'rejected'; rule?: string; scope?: string; counter?: string }) => Promise<void> }) {
  const [open, setOpen] = useState<string | null>(null)
  const [rule, setRule] = useState('')
  const [scope, setScope] = useState('')
  const [counter, setCounter] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const go = async (r: { id: string; klass: 'long_term' | 'project' | 'rejected'; rule?: string; scope?: string; counter?: string }) => {
    setErr(null)
    try { await onDone?.(r); setOpen(null) } catch (e) { setErr((e as Error).message) }
  }
  return (
    <div className="border-b border-line px-4 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">From what you did</div>
      <ul className="mt-1 space-y-1.5">
        {items.map((s) => (
          <li key={s.id} className="text-[12px] text-zinc-300">
            <span className="text-muted">{s.said}</span> — remember “{s.rule}”?
            {open === s.id ? (
              <div className="mt-1 space-y-1">
                <input value={rule} onChange={(e) => setRule(e.target.value)} className="w-full rounded border border-line bg-ink px-2 py-0.5 text-[12px]" />
                <input value={scope} onChange={(e) => setScope(e.target.value)} placeholder="when it applies" className="w-full rounded border border-line bg-ink px-2 py-0.5 text-[12px]" />
                <input value={counter} onChange={(e) => setCounter(e.target.value)} placeholder="when it doesn't" className="w-full rounded border border-line bg-ink px-2 py-0.5 text-[12px]" />
                <div className="flex gap-1.5">
                  <button type="button" className="rounded bg-accent px-2 py-0.5 text-[11px] font-semibold text-accent-ink" onClick={() => go({ id: s.id, klass: 'long_term', rule, scope, counter })}>Every video</button>
                  <button type="button" className="rounded border border-line px-2 py-0.5 text-[11px]" onClick={() => setOpen(null)}>Cancel</button>
                </div>
                {err && <div className="text-[11px] text-rose-300">{err}</div>}
              </div>
            ) : (
              <span className="ml-1 inline-flex gap-1">
                <button type="button" className="rounded border border-line px-1.5 text-[11px] hover:bg-raised" onClick={() => { setOpen(s.id); setRule(s.rule); setScope(''); setCounter('') }}>Every video…</button>
                <button type="button" className="rounded border border-line px-1.5 text-[11px] hover:bg-raised" onClick={() => go({ id: s.id, klass: 'project', rule: s.rule })}>Just this one</button>
                <button type="button" className="rounded border border-line px-1.5 text-[11px] text-muted hover:bg-raised" onClick={() => go({ id: s.id, klass: 'rejected' })}>No</button>
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
