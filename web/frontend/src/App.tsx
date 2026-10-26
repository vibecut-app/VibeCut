import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { api, type AIEstimate, type AIState, type ChatProvider, type MakeJob, saving } from './api'
import { AISwitch } from './components/AISwitch'
import { Chat, type ChatItem, type SendExtra } from './components/Chat'
import { KIND_META, partsOf } from './overlayDraw'
import { loadProfile } from './profile'
import { StyleQuestions } from './components/StyleQuestions'
import { composeBrief, sayPicks, type Picks } from './brief'
import { Export } from './components/Export'
import { Remix } from './components/Remix'
import { BorrowStyle } from './components/BorrowStyle'
import { Overlays } from './components/Overlays'
import { TalkCut } from './components/TalkCut'
import { Keys } from './components/Keys'
import { Player } from './components/Player'
import { PauseChat } from './components/PauseChat'
import { PaceButton } from './components/PaceButton'
import { Setup, type SetupData } from './components/Setup'
import { SaveRecipe } from './components/SaveRecipe'
import { LengthButton } from './components/LengthButton'
import { PreferCards } from './components/PreferCards'
import type { OverlayEdit } from './components/OverlayCanvas'
import { Menu, SwapPicker, type MenuItem } from './components/Menus'
import { Music } from './components/Music'
import type { ClassifyReq } from './components/Remember'
import { Shelf } from './components/Shelf'
import { SmoothButton, Story, type PlayItem, type Selection } from './components/Story'
import { CutNotes } from './components/CutNotes'
import { Timeline, type Marks } from './components/Timeline'
import { Inspector, type InspectorTab, type JoinPick } from './components/Inspector'
import { PreviewBar, type FrameChoice } from './components/PreviewBar'
import { Handle, useLayout } from './components/Split'
import { Icon, type IconName } from './components/icons'
import { Footage, type Importing } from './components/Footage'
import { fromDataTransfer, fromInput, takeHandoff, takeRefs, type Picked } from './drop'
import { bytes, cents, uid } from './format'
import { clock, locate, toSource, type SeqItem } from './sequence'
import { cutWhilePlaying, step } from './snap'
import { byKey } from './joinView'
import { go } from './router'
import { deriveStage, reached, STAGES, type Stage } from './stage'
import { phStore, snapStore, transport, transportStore, useStore } from './transport'
import { Button, Confirm, cx, Wordmark } from './ui'
import type { Capabilities, Clip, Msg, Option, Overlay, OverlayKind, Overlays as OverlayData, Segment, Session, StyleAnswers, StyleQuestion, TimelineData } from './types'

const hello: Msg = {
  id: 'hello', role: 'app', at: 0,
  text: 'Your edit is ready. Tell me what to change: “the opening is too slow”, “take out the market”, “end on the sunset”. Everything can be undone.',
}
const EMPTY_TL: TimelineData = { fps: 30, total: 0, items: [], targets: [], grid: null }
const CHECK_ASK = 'Check my whole edit'

const EMPTY_OVERLAYS: OverlayData = {
  items: [], findings: [], style: { font: 'Clean', color: '#ffffff', accent: '#b9d9eb', captions: 'bottom', backing: 'shadow' },
}
const NO_CAPS: Capabilities = { llm: false, speech: false, vision: 'unavailable', links: false, music_folder: null, platform: '' }
const shortDate = (iso: string | null | undefined) => {
  const m = iso?.match(/^(\d{4})-(\d\d)-(\d\d)/)
  if (!m) return null
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).replace(/,/g, '').toUpperCase()
}
const r3 = (x: number) => Math.round(x * 1000) / 1000

type Queue = { source: string; items: PlayItem[]; index: number }

function useNarrow(px = 1100): boolean {
  const [n, setN] = useState(() => window.innerWidth < px)
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${px - 1}px)`)
    const f = () => setN(mq.matches)
    mq.addEventListener('change', f)
    return () => mq.removeEventListener('change', f)
  }, [px])
  return n
}

// One project's workspace. The stage in the middle (Footage · Brief ·
// Rough cut · Story) is derived from the project's state, never set by
// hand; the stepper only lets you look back at an earlier one.
export default function App({ id, view }: { id: string; view: 'story' | 'frames' }) {
  const level = view
  const setLevel = (k: 'story' | 'frames') => go({ kind: 'project', id, view: k })
  const narrow = useNarrow()
  const [opened, setOpened] = useState<'loading' | 'ok' | string>('loading')
  const [clips, setClips] = useState<Clip[]>([])
  const [session, setSession] = useState<Session | null>(null)
  const [local, setLocal] = useState<Msg[]>([hello])
  const [importing, setImporting] = useState<Importing>(null)
  const [dragging, setDragging] = useState(false)
  const [pending, setPending] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)   // Frames: timeline entry
  const [storySel, setStorySel] = useState<Selection>(null)
  const [menu, setMenu] = useState<{ kind: 'story-shot' | 'frames-shot' | 'gap'; key: string; anchor: DOMRect } | null>(null)
  const [selAudio, setSelAudio] = useState<string | null>(null)   // Frames: a sound strip (extract audio)
  const [selJoin, setSelJoin] = useState<string | null>(null)     // Frames: the cut after this entry (its transition)
  const [insTab, setInsTab] = useState<InspectorTab>('edit')      // Frames: the inspector on the right
  const [swap, setSwap] = useState<{ key: string; thumb: string; id: string } | null>(null)
  const [undoable, setUndoable] = useState<{ turn: number; text: string } | null>(null)
  // The rough cut and its gate.
  const [approving, setApproving] = useState(false)
  const [segment, setSegment] = useState<Segment | null>(null)
  const [queue, setQueue] = useState<Queue | null>(null)
  const [marks, setMarks] = useState<Marks>({ in: null, out: null })
  const [flash, setFlash] = useState<string | null>(null)
  const [alt, setAlt] = useState(false)
  const [help, setHelp] = useState(false)
  const [selOverlay, setSelOverlay] = useState<string | null>(null)
  // Frames: the panel beside the rail on the left (closed by clicking its item again)
  const [side, setSide] = useState<'media' | 'text' | 'music' | 'chat' | null>(() => (window.innerWidth < 1100 ? null : 'media'))
  const [layout, setSize] = useLayout()
  const stageRef = useRef<HTMLDivElement>(null)
  const isSaving = useSyncExternalStore(saving.subscribe, saving.get)
  const [exporting, setExporting] = useState(false)
  const [remixing, setRemixing] = useState(false)
  const [referencing, setReferencing] = useState(false)
  const [talkOpen, setTalkOpen] = useState(false)
  const [more, setMore] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)     // narrow screens: the chat as a drawer
  const [restart, setRestart] = useState(false)
  const [renaming, setRenaming] = useState(false)
  // Looking back at an earlier stage without leaving the story.
  const [peek, setPeek] = useState<Stage | null>(null)
  // The style questions after the first description.
  const [asking, setAsking] = useState<{ text: string; questions: StyleQuestion[] | null; tailored: boolean } | null>(null)
  const dragDepth = useRef(0)
  const videoRef = useRef<HTMLVideoElement>(null)
  const backRef = useRef<HTMLVideoElement>(null)
  const veilRef = useRef<HTMLDivElement>(null)
  const musicRef = useRef<HTMLAudioElement>(null)
  const mixRef = useRef<HTMLAudioElement>(null)
  const [boardPlay, setBoardPlay] = useState(false)
  const [boardShot, setBoardShot] = useState<string | null>(null)
  const tr = useStore(transportStore)
  const tl = session?.timeline ?? EMPTY_TL
  const fr = 1 / tl.fps
  const ovData = session?.overlays ?? EMPTY_OVERLAYS
  const caps = session?.capabilities ?? NO_CAPS
  const brief = session?.brief ?? null
  const parts = useMemo(() => partsOf(tl.items), [tl.items])
  const inEdit = useMemo(() => new Set(tl.items.flatMap((x) => (x.clip_id ? [x.clip_id] : []))), [tl.items])
  const overlayView = useMemo(() => ({ items: ovData.items, style: ovData.style, parts }), [ovData, parts])
  const profileInitial = useMemo(() => {
    try { return loadProfile(window.localStorage).profile.name.trim().charAt(0).toUpperCase() || '☺' } catch { return '☺' }
  }, [])


  const refresh = useCallback(async () => {
    const [p, s] = await Promise.all([api.project(), api.session()])
    setClips(p.clips)
    setSession(s)
  }, [])

  useEffect(() => {
    let live = true
    api.openProject(id)
      .then(async (r) => { if (!live) return; setSession(r.session); const p = await api.project(); if (live) { setClips(p.clips); setOpened('ok') } })
      .catch((e) => { if (live) setOpened((e as Error).message || 'This project could not be opened.') })
    transport.attach(videoRef.current, backRef.current, veilRef.current)
    return () => { live = false; transport.stop() }
  }, [id])
  useEffect(() => { transport.setItems(tl.items, tl.total) }, [tl])
  // Music by default is picked in the background (online it can take a
  // minute); poll until it lands as a turn, then offer Undo for it.
  const bedStage = session?.bed?.stage
  useEffect(() => {
    if (bedStage !== 'looking') return
    let stop = false
    const timer = window.setInterval(async () => {
      try {
        const s = await api.session()
        if (stop) return
        setSession(s)
        if (s.bed?.stage !== 'looking') {
          window.clearInterval(timer)
          if (s.bed?.stage === 'done') offerUndo(s)
          else if (s.bed?.why) note(s.bed.why)
        }
      } catch { /* the next tick tries again */ }
    }, 1500)
    return () => { stop = true; window.clearInterval(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bedStage])
  useEffect(() => {
    const byId = new Map(clips.map((c) => [c.id, c.samples]))
    transport.setSamples((id, t) => {
      const s = byId.get(id)
      if (!s?.times.length) return null
      let k = 0
      s.times.forEach((x, i) => { if (Math.abs(x - t) < Math.abs(s.times[k] - t)) k = i })
      return `${s.base}${k}`
    })
  }, [clips])
  const wfState = session?.workflow?.state
  const atGate = wfState === 'cut-review'

  // ---- where we are ----------------------------------------------------------
  const stage: Stage = deriveStage({
    clips: clips.length, workflow: wfState ?? 'intake', brief: !!brief,
    proposals: !!session?.proposals, board: !!session?.board,
  })
  const done = reached({ clips: clips.length, workflow: wfState ?? 'intake', brief: !!brief, proposals: !!session?.proposals, board: !!session?.board })
  const shown: Stage = peek && done.includes(peek) ? peek : stage
  // The style step has no page of its own (sarah, 2026-10-07: "delete this
  // entire page"): its questions open over the stacks, and once answered the
  // rough cut is next. What the video is comes from the clips (pitch.guess).
  const screen: Stage = shown === 'brief' ? (brief ? 'cut' : 'footage') : shown
  useEffect(() => { if (peek && !done.includes(peek)) setPeek(null) }, [peek, done])
  useEffect(() => { if (shown !== 'story' && level === 'frames') setLevel('story') }, [shown]) // eslint-disable-line react-hooks/exhaustive-deps
  // Once a story is chosen the edit lives in Frames (sarah, 2026-10-04), and
  // since 2026-10-07 only there: the other stories open from More and close
  // back into Frames. No Story / Frames switch.
  const [othersOpen, setOthersOpen] = useState(false)
  useEffect(() => {
    if (session?.board && shown === 'story' && !talkOpen && level === 'story' && !othersOpen) setLevel('frames')
  }, [session?.board, shown, talkOpen, level, othersOpen])
  const showStep = (s: Stage) => { setPeek(s === stage ? null : s); setMenu(null); stopQueue(); setSegment(null); if (s !== 'story') transport.stop() }

  const cutOverride = async (target: string, action: string, range?: [number, number]) => {
    await api.override(target, action, range)
    await refresh()
  }
  const approveCut = async () => {
    setApproving(true)
    try {
      const s = await api.approve()
      setSession(s)
      setPeek(null)
      // The creator already said what the video is and how it should feel.
      if (s.brief && !s.proposals && !s.board) await send(s.brief.message, s.brief.style)
    } catch (e) { note((e as Error).message) } finally { setApproving(false) }
  }
  // The rough trim has no page any more (sarah, 2026-10-07): once the style
  // questions are answered it's approved as it stands and the story is built.
  // Every trim stays changeable in Frames by dragging a shot's ends.
  const autoApproved = useRef(false)
  useEffect(() => {
    // after the clips load: building the story needs them
    if (atGate && brief && clips.length && !approving && !autoApproved.current) { autoApproved.current = true; approveCut() }
    if (!atGate) autoApproved.current = false
  }, [atGate, !!brief, clips.length > 0]) // eslint-disable-line react-hooks/exhaustive-deps
  // Past the gate with the questions answered but no story yet (the build was
  // interrupted, or the page reloaded mid-way): build it, once.
  const built = useRef(false)
  const waiting = !!wfState && !['intake', 'indexing', 'rough-cut', 'cut-review'].includes(wfState)
    && !!brief && !session?.proposals && !session?.board
  useEffect(() => {
    if (waiting && clips.length && !pending && !approving && !built.current) { built.current = true; send(brief!.message, brief!.style) }
    if (!waiting) built.current = false
  }, [waiting, clips.length > 0, !!pending, approving]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    transport.attach(videoRef.current, backRef.current, veilRef.current)
    if (level === 'frames') transport.seek(phStore.get())
    else transport.stop()
    setMenu(null)
  }, [level, shown])
  useEffect(() => { transport.audio = session?.music ? musicRef.current : null }, [session?.music])
  const mixKey = session?.mix?.key
  const transList = session?.mix?.transitions
  useEffect(() => { transport.setTransitions(byKey(transList), tl.fps) }, [transList, tl.fps])
  useEffect(() => { transport.mix = mixKey ? mixRef.current : null; transport.mixBroken = false }, [mixKey])
  useEffect(() => { if (!tr.playing) setBoardPlay(false) }, [tr.playing])
  useEffect(() => {
    if (!boardPlay) { setBoardShot(null); return }
    const show = () => {
      const k = locate(tl.items, phStore.get())
      const it = k < 0 ? null : tl.items[k]
      setBoardShot(it && it.kind === 'shot' ? it.key : null)
    }
    show()
    return phStore.subscribe(show)
  }, [boardPlay, tl.items])

  const say = useCallback((text: string, busy = false) => {
    const id = uid()
    setLocal((ms) => [...ms, { id, role: 'app', text, busy, at: Date.now() }])
    return (next: string, stillBusy = false) =>
      setLocal((ms) => ms.map((m) => (m.id === id ? { ...m, text: next, busy: stillBusy } : m)))
  }, [])

  const flashTimer = useRef<number | undefined>(undefined)
  const undoTimer = useRef<number | undefined>(undefined)
  const note = (text: string) => {
    setFlash(text)
    window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => setFlash(null), 2800)
  }

  // ---- chat ------------------------------------------------------------------
  const chatItems: ChatItem[] = useMemo(() => {
    const out: (ChatItem & { at: number })[] = [
      ...local.map((m) => ({ type: 'local' as const, msg: m, at: m.at })),
      ...(session?.turns ?? []).map((t) => ({ type: 'turn' as const, turn: t, at: t.at * 1000 })),
    ]
    return out.sort((a, b) => a.at - b.at)
  }, [local, session])

  // extra comes only from the chat box: the moment a message is about and the
  // cost Send showed. The app's own sends (the first story) carry neither, so
  // on the course key they're built by the free rules, never the AI.
  const chatRid = useRef<string | null>(null)
  const stopped = useRef<Set<string>>(new Set())
  const send = async (text: string, style?: StyleAnswers, extra?: SendExtra) => {
    if (!clips.length) {
      setLocal((ms) => [...ms, { id: uid(), role: 'user', text, at: Date.now() }])
      say('Add some clips first — then there’s something to arrange.')
      return
    }
    // The first description: ask a few style questions before anything is built.
    if (!style && !session?.board && !session?.proposals && !brief) { askStyle(text); return }
    const rid = uid()
    chatRid.current = rid
    setPending(text)
    const mine = { id: uid(), role: 'user' as const, text, at: Date.now() }
    try {
      const r = await api.chat(text, style, extra?.ai_ok ?? null, extra?.t ?? null, rid)
      setSession(r)
      if (stopped.current.has(rid)) {
        stopped.current.delete(rid)
        // Stop came too late: the answer had already changed the edit
        if (!r.stopped) say('It had already made that change when you pressed Stop. Its Undo is right above.')
        else if (r.stop_cost) say(`The stopped answer cost ${cents(r.stop_cost)}.`)
      } else {
        setPeek(null)
      }
    } catch (e) {
      const err = e as Error & { status?: number }
      if (stopped.current.delete(rid)) { if (extra) api.session().then(setSession, () => {}); return }
      setLocal((ms) => [...ms, mine, {
        id: uid(), role: 'app', at: Date.now(),
        text: extra ? `That didn’t work: ${err.message} Nothing in your edit changed.` : err.message,
        // the AI was out of reach or its answer was unusable: worth one more go (409s aren't)
        retry: extra && (err.status == null || err.status >= 500) ? text : undefined,
      }])
      // a failed answer can still have been paid for: the total moves
      if (extra) api.session().then(setSession, () => {})
    } finally {
      if (chatRid.current === rid) { chatRid.current = null; setPending(null) }
    }
  }
  // Check my edit: the AI looks over every shot of the cut at once and fixes
  // what's clearly wrong, as one undoable turn. aiOk is the price the button showed.
  const [checking, setChecking] = useState(false)
  const checkEdit = async (aiOk: number) => {
    const rid = uid()
    chatRid.current = rid
    setPending(CHECK_ASK)
    setChecking(true)
    try {
      const r = await api.check(aiOk, rid)
      setSession(r)
      if (stopped.current.delete(rid)) {
        if (!r.stopped) say('It had already made its changes when you pressed Stop. Their Undo is right above.')
        else if (r.stop_cost) say(`The stopped check cost ${cents(r.stop_cost)}.`)
      }
    } catch (e) {
      if (stopped.current.delete(rid)) { api.session().then(setSession, () => {}); return }
      setLocal((ms) => [...ms, { id: uid(), role: 'user', text: CHECK_ASK, at: Date.now() },
        { id: uid(), role: 'app', at: Date.now(), text: `That didn’t work: ${(e as Error).message} Nothing in your edit changed.` }])
      api.session().then(setSession, () => {})
    } finally {
      setChecking(false)
      if (chatRid.current === rid) { chatRid.current = null; setPending(null) }
    }
  }
  // Stop: the box is free again at once; the answer, when it lands, changes nothing.
  const stopChat = () => {
    const rid = chatRid.current
    if (!rid || !pending) return
    stopped.current.add(rid)
    chatRid.current = null
    setLocal((ms) => [...ms, { id: uid(), role: 'user', text: pending, at: Date.now() },
      { id: uid(), role: 'app', text: 'Stopped. Nothing in your edit changed.', at: Date.now() }])
    setPending(null)
    api.chatStop(rid).catch(() => {})
  }

  const askStyle = (text: string) => {
    setAsking({ text, questions: null, tailored: false })
    api.questions(text)
      .then((r) => setAsking((a) => a && a.text === text ? { ...a, questions: r.questions, tailored: r.tailored } : a))
      .catch(() => setAsking((a) => a && a.text === text ? { ...a, questions: [] } : a))
  }
  // No "what's this video about?" any more (sarah, 2026-10-06): the clips
  // say it (day / trip, what's in them), and the questions open straight away.
  // No questions either (sarah, 2026-10-07): the suggested length, captions
  // on, straight to the stories. Length and Captions are in Frames.
  // Two picks remain (2026-10-10): the frame and the look, in one popup
  // with the footage's own defaults; "Make my video" builds the rest.
  const autoBrief = useRef(false)
  const [setup, setSetup] = useState<{ data: SetupData | null; busy: boolean; progress?: MakeJob | null } | null>(null)
  const playOnLand = useRef(false)   // the first thing after Make my video is the video, playing
  // Watch: the video full-size with four chips and Download; the editor
  // (rail, inspector, timeline) waits behind one Fine-tune link. A made
  // video opens here; a hand-cut one opens in the editor.
  const [watching, setWatching] = useState<boolean | null>(null)
  const [savingRecipe, setSavingRecipe] = useState(false)    // Save as my recipe (recipes.py)
  useEffect(() => {
    if (watching === null && session?.board) setWatching(session.board.option === 'made' || session.board.option === 'remix')
  }, [session?.board, watching])
  const startQuestions = () => {
    if (asking || autoBrief.current || setup || frontDoor.current || remixing) return
    setSetup({ data: null, busy: false })
    api.setup().then((d) => setSetup((x) => x && { ...x, data: d }), (e) => { note((e as Error).message); setSetup(null) })
  }
  // Make my video (2026-10-17): the one pipeline runs as a job; the dialog
  // shows where it is; when it lands the edit opens in Frames and plays.
  // The AI switch: off by default; on, Make shows this edit's cost first and
  // only a Make carrying that estimate lets the AI plan it (backend oai.py).
  const [ai, setAI] = useState<AIState | null>(null)
  const [estimate, setEstimate] = useState<AIEstimate | null>(null)
  useEffect(() => {
    // read again when the window comes back: the switch may have changed elsewhere
    const read = () => { api.ai().then(setAI, () => setAI(null)) }
    read()
    window.addEventListener('focus', read)
    return () => window.removeEventListener('focus', read)
  }, [])
  const toggleAI = async (on: boolean) => {
    try { setAI(await api.setAI(on)) } catch (e) { note((e as Error).message) }
  }
  // Who answers the chat (backend llm.chat_provider): OpenAI on the course
  // key while the switch is on, else Claude if its key is set. The chat box
  // reads what one message costs before anything is sent, again whenever the
  // edit changes (the prompt carries the edit).
  const chatWho: ChatProvider = ai?.available && ai.on ? 'openai' : caps.llm ? 'claude' : null
  const turnsKey = `${session?.turns.length ?? 0}/${session?.turns.filter((x) => x.undone).length ?? 0}`
  useEffect(() => {
    setEstimate(null)
    if (!setup || !ai?.on || setup.busy) return
    let live = true
    api.makeEstimate().then((e) => live && setEstimate(e), (e) => live && note((e as Error).message))
    return () => { live = false }
  }, [!!setup, ai?.on]) // eslint-disable-line react-hooks/exhaustive-deps
  const makeIt = async (format: string, look: string, music: boolean = true, vibe: string | null = null, aiCost: number | null = null) => {
    if (autoBrief.current) return
    autoBrief.current = true
    setSetup((x) => x && { ...x, busy: true })
    try {
      // the price the button showed goes with it; without one the rules make the edit, free
      let job = await api.make({ format, look, music, vibe, ai_ok: aiCost })
      setSetup((x) => x && { ...x, progress: job })
      while (job.stage !== 'done' && job.stage !== 'error') {
        await new Promise((r) => window.setTimeout(r, 700))
        job = await api.makeStatus(job.id)
        setSetup((x) => x && { ...x, progress: job })
      }
      if (job.stage === 'error') throw new Error(job.error ?? 'Making the video failed')
      playOnLand.current = true
      setSession(await api.session())
      setSetup(null)
      setWatching(true)
      setLevel('frames')
    } catch (e) {
      note((e as Error).message)
      setSetup((x) => x && { ...x, busy: false, progress: null })
    } finally {
      autoBrief.current = false
    }
  }
  useEffect(() => {
    if (!playOnLand.current || level !== 'frames' || !session?.board || !tl.total) return
    playOnLand.current = false
    const t = window.setTimeout(() => { snapStore.set(null); transport.seek(0); transport.play(1) }, 400)
    return () => window.clearTimeout(t)
  }, [level, session?.board, tl.total])
  // Opening a project that's waiting on them: the questions are simply there.
  useEffect(() => {
    if (shown === 'brief' && !brief && clips.length && !asking) startQuestions()
  }, [shown, !!brief, clips.length > 0]) // eslint-disable-line react-hooks/exhaustive-deps
  const answered = async (picks: Picks, extra: string) => {
    if (!asking?.questions) return
    const { text, questions } = asking
    setAsking(null)
    const b = { ...composeBrief(text, questions, picks, extra), said: sayPicks(questions, picks) }
    try {
      const s = await api.brief(b.message, b.style, b.said)
      setSession(s)
      setPeek(null)
      // Past the gate already (approved earlier, nothing built): build now.
      if (s.workflow.state !== 'cut-review' && !s.proposals && !s.board) await send(b.message, b.style)
    } catch (e) { note((e as Error).message) }
  }

  const offerUndo = (s: Session) => {
    const t = s.turns.at(-1)
    if (t?.skipped.length) note(`Couldn’t: ${t.skipped[0]}`)
    if (t && t.lines.length && !t.skipped.length) {
      setUndoable({ turn: t.id, text: t.lines.map((l) => l.text).join(' · ') })
      window.clearTimeout(undoTimer.current)
      undoTimer.current = window.setTimeout(() => setUndoable(null), 7000)
    }
  }

  const run = async (ops: Record<string, unknown>[], label: string) => {
    try {
      const s = await api.ops(ops, label)
      setSession(s)
      offerUndo(s)
      return s
    } catch (e) {
      note(`Couldn’t apply that: ${(e as Error).message}`)
      return null
    }
  }

  const toggle = async (turn: number) => { setSession(await api.toggle(turn)) }
  const lastDone = [...(session?.turns ?? [])].reverse().find((x) => !x.undone && x.has_ops)
  const lastUndone = [...(session?.turns ?? [])].reverse().find((x) => x.undone && x.has_ops)
  const undoRedo = (redo: boolean) => {
    const target = redo ? lastUndone : lastDone
    if (target) toggle(target.id)
  }
  const classify = async (req: ClassifyReq) => { setSession(await api.classify(req)) }
  const changeRule = async (id: string, action: 'forget' | 'narrow') => {
    try { setSession(await api.rule(id, action)) } catch (e) { note((e as Error).message) }
  }

  // ---- import ----------------------------------------------------------------
  const runImport = useCallback(async (paths: string[], picked: number, sizeText: string) => {
    let job = await api.import(paths)
    while (job.stage !== 'done' && job.stage !== 'error') {
      const frac = job.stage === 'looking' ? 0.95 : 0.3 + 0.6 * (job.done / Math.max(1, job.total))
      setImporting({ frac, text: job.stage === 'looking'
        ? `Read ${job.total} clip${job.total === 1 ? '' : 's'}. Looking at what’s in each shot…`
        : `Reading clip ${Math.min(job.done + 1, job.total)} of ${job.total}${sizeText} — shots, capture time, place, quality, sound…` })
      await new Promise((r) => setTimeout(r, 250))
      job = await api.job(job.id)
    }
    await refresh()
    const added = job.total - job.errors.length
    if (job.stage === 'error') throw new Error(job.errors.at(-1)?.error ?? 'The import failed.')
    return { added, known: job.known, errors: job.errors.length, picked }
  }, [refresh])

  const importPicked = useCallback(async (picked: Picked[]) => {
    if (!picked.length) { note('No .mp4 or .mov files in that drop.'); return }
    if (importing) return
    // Stay on the footage screen while it reads: the creator sees the clips
    // land and moves on when they choose to, not when the machine is done.
    if (shown === 'footage') setPeek('footage')
    const size = picked.reduce((n, p) => n + p.file.size, 0)
    setImporting({ frac: 0.03, text: `Found ${picked.length} clip${picked.length === 1 ? '' : 's'} (${bytes(size)}). Finding ${picked.length === 1 ? 'it' : 'them'} on disk…` })
    try {
      const loc = await api.locate(picked.map((p) => ({
        name: p.file.name, size: p.file.size, mtime: p.file.lastModified, relpath: p.relpath,
      })))
      const paths = picked.map((p) => loc.resolved[p.relpath]).filter(Boolean)
      const missing = picked.filter((p) => !loc.resolved[p.relpath])
      if (missing.length) {
        const batch = uid()
        let k = 0
        for (const p of missing) {
          setImporting({ frac: 0.05 + 0.25 * (k / missing.length), text: `Copying ${missing.length} clip${missing.length === 1 ? '' : 's'} I couldn’t find on disk into the local cache… ${k}/${missing.length}` })
          paths.push((await api.upload(p.file, p.relpath, batch)).path)
          k++
        }
      }
      const r = await runImport(paths, picked.length, ` (${bytes(size)})`)
      const known = r.known ? ` (${r.known} already here)` : ''
      const line = `Added ${r.added} clip${r.added === 1 ? '' : 's'}${known}${r.errors ? ` · ${r.errors} couldn’t be read` : ''}.`
      if (stage === 'story') say(`${line} ${session?.board ? 'They’re on the shelf — nothing in your story changed.' : 'They’re on the shelf.'}`)
      else note(line)
    } catch (e) {
      note(`Import failed: ${(e as Error).message}`)
    } finally {
      setImporting(null)
    }
  }, [importing, runImport, say, stage, shown, session?.board])

  // Clips picked on the home page before this video existed: read them now.
  // Reels pasted beside them (the front door, plan step 4) wait until the
  // clips are read, then a Remix starts with them and lands as the story.
  const frontDoor = useRef<string[] | null>(null)
  const [frontLinks, setFrontLinks] = useState<string | null>(null)
  useEffect(() => {
    if (opened !== 'ok') return
    frontDoor.current = takeRefs()
    const p = takeHandoff()
    if (p?.length) importPicked(p)
  }, [opened]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!frontDoor.current || importing || !clips.length || stage === 'footage') return
    const links = frontDoor.current.join('\n')
    frontDoor.current = null
    transport.stop(); videoRef.current?.pause(); stopQueue(); setMenu(null)
    setFrontLinks(links)
    setRemixing(true)
  }, [importing, clips.length, stage]) // eslint-disable-line react-hooks/exhaustive-deps

  const retryImport = async (paths: string[]) => {
    if (importing) return
    setImporting({ frac: 0.03, text: `Trying ${paths.length} file${paths.length === 1 ? '' : 's'} again…` })
    try { const r = await runImport(paths, paths.length, ''); note(`Added ${r.added} clip${r.added === 1 ? '' : 's'}${r.errors ? ` · ${r.errors} still can’t be read` : ''}.`) }
    catch (e) { note((e as Error).message) }
    finally { setImporting(null) }
  }

  useEffect(() => {
    const isFiles = (e: DragEvent) => e.dataTransfer?.types.includes('Files')
    const enter = (e: DragEvent) => { if (isFiles(e)) { dragDepth.current++; setDragging(true) } }
    const leave = (e: DragEvent) => { if (isFiles(e) && --dragDepth.current <= 0) { dragDepth.current = 0; setDragging(false) } }
    const over = (e: DragEvent) => { if (isFiles(e)) e.preventDefault() }
    const drop = async (e: DragEvent) => {
      if (!isFiles(e)) return
      e.preventDefault()
      dragDepth.current = 0
      setDragging(false)
      importPicked(await fromDataTransfer(e.dataTransfer!))
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragleave', leave)
    window.addEventListener('dragover', over)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('dragover', over)
      window.removeEventListener('drop', drop)
    }
  }, [importPicked])

  // ---- previews (shelf, storyboard cards): a queue of spans ------------------
  const stopQueue = () => { setQueue(null) }
  const playAt = (q: Queue, k: number) => {
    const it = q.items[k]
    if (!it) { stopQueue(); videoRef.current?.pause(); return }
    transport.stop()
    setQueue({ ...q, index: k })
    setSegment({ key: uid(), clipId: it.clipId, start: it.start, end: it.end, autoplay: true })
  }
  const playSource = (source: string, list: PlayItem[]) => {
    if (source === 'board') {
      if (boardPlay) { transport.stop(); return }
      stopQueue()
      setSegment(null)
      transport.attach(videoRef.current, backRef.current, veilRef.current)
      transport.seek(0)
      transport.play(1)
      setBoardPlay(true)
      return
    }
    if (boardPlay) transport.stop()
    if (queue?.source === source) { stopQueue(); videoRef.current?.pause(); return }
    if (list.length) playAt({ source, items: list, index: 0 }, 0)
  }
  // A shot or a part of the story plays as the edit, not as its raw clip, so
  // its words on screen, joins and sound are what you see.
  const until = useRef<number | null>(null)
  const playEdit = (from: number, to: number) => {
    stopQueue()
    setSegment(null)
    transport.stop()
    transport.attach(videoRef.current, backRef.current, veilRef.current)
    transport.seek(from)
    until.current = to
    transport.play(1)
    setBoardPlay(true)
  }
  useEffect(() => phStore.subscribe(() => {
    if (until.current != null && phStore.get() >= until.current - 0.03) { until.current = null; transport.stop() }
  }), [])
  useEffect(() => { if (!tr.playing) until.current = null }, [tr.playing])
  const spanOf = (keys: string[]) => {
    const its = tl.items.filter((x) => keys.includes(x.key))
    return its.length ? [Math.min(...its.map((x) => x.seq_start)), Math.max(...its.map((x) => x.seq_end))] as const : null
  }
  const preview = (clipId: string, start: number, end: number, shotId: string) => {
    transport.lend()
    stopQueue()
    setSegment({ key: shotId + uid(), clipId, start, end, autoplay: true })
  }
  const timelineOwns = () => { stopQueue(); setSegment(null) }

  // ---- the edit at the playhead ------------------------------------------------
  const tlRef = useRef(tl)
  tlRef.current = tl
  const here = (t: number) => {
    const items = tlRef.current.items
    const k = locate(items, t)
    return k < 0 ? null : items[k]
  }

  const cutAt = async (t: number, why = '') => {
    const it = here(t)
    if (!it) return
    if (it.kind === 'gap') { note('Nothing to cut in a gap'); return }
    if (t - it.seq_start < fr / 2 || it.seq_end - t < fr / 2) { note(`Already a cut at ${clock(t)}`); return }
    const s = await run([{ op: 'split', shot: it.key, at: r3(toSource(it, t)) }], `You cut shot ${it.n} at ${clock(t)}`)
    if (s) note(why || `Cut at ${clock(t)}`)
  }

  const cut = () => {
    const t = phStore.get()
    if (transportStore.get().playing) {
      const r = cutWhilePlaying(tlRef.current.targets, t)
      const d = r.t - t
      cutAt(r.t, r.target ? `Cut on ${r.target.label} (${d >= 0 ? '+' : ''}${d.toFixed(2)}s from your tap)`
        : `Cut at ${clock(t)} — nothing to snap to nearby`)
    } else {
      cutAt(t)
    }
  }

  const trimToPlayhead = async (edge: 'in' | 'out', leaveGap: boolean) => {
    const t = phStore.get()
    const it = here(edge === 'out' ? t - 1e-6 : t)
    if (!it || it.kind === 'gap') { note('Put the playhead inside a shot'); return }
    const s = await run([{ op: 'trim', shot: it.key, edge, to: r3(toSource(it, t)), leave_gap: leaveGap || undefined }],
      `You trimmed the ${edge === 'in' ? 'start' : 'end'} of shot ${it.n} to the playhead${leaveGap ? ' (gap left)' : ''}`)
    if (s && edge === 'in' && !leaveGap) transport.seek(it.seq_start)
  }

  const trimBy = (units: number, unit: 'frame' | 'second' | 'beat') => {
    const t = phStore.get()
    const it = here(t)
    if (!it || it.kind === 'gap') { note('Put the playhead inside a shot'); return }
    const g = tlRef.current.grid
    if (unit === 'beat' && !g) { note('No beat grid — pick a track with a steady tempo under “Music”'); return }
    const size = unit === 'frame' ? fr : unit === 'second' ? 1 : 60 / g!.bpm
    const word = unit === 'frame' ? 'frame' : unit === 'second' ? 'second' : 'beat'
    run([{ op: 'trim', shot: it.key, edge: 'out', to: r3(it.src_end + units * size) }],
      `You made shot ${it.n} one ${word} ${units < 0 ? 'shorter' : 'longer'}`)
  }

  const deleteSelection = async (leaveGap: boolean) => {
    const items = tlRef.current.items
    if (marks.in != null && marks.out != null && marks.out > marks.in) {
      let a = marks.in
      let z = marks.out
      const ia = items[locate(items, a)]
      const iz = items[locate(items, z - 1e-6)]
      if (ia.kind === 'gap') a = ia.seq_start
      if (iz.kind === 'gap') z = iz.seq_end
      const s = await run([{
        op: 'drop_range', from_shot: ia.key, from_at: r3(toSource(ia, a)),
        to_shot: iz.key, to_at: r3(toSource(iz, z)), leave_gap: leaveGap || undefined,
      }], `You ${leaveGap ? 'lifted' : 'removed'} ${clock(a)}–${clock(z)}`)
      if (s) { setMarks({ in: null, out: null }); transport.seek(a) }
      return
    }
    if (selected) {
      const it = items.find((i) => i.key === selected)
      await run([{ op: 'drop_shot', shot: selected, leave_gap: leaveGap || undefined }],
        `You ${leaveGap ? 'lifted' : 'deleted'} ${it?.kind === 'gap' ? 'a gap' : `shot ${it?.n}`}`)
      setSelected(null)
      return
    }
    note('Select a shot, or mark In (I) and Out (O), then Delete')
  }

  const goTo = (t: number, target: Parameters<typeof snapStore.set>[0] = null) => {
    transport.seek(t)
    snapStore.set(target)
  }

  // ---- keyboard: industry conventions ----------------------------------------
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (exporting || referencing || remixing || restart || renaming) return
      if (e.key === 'Alt') setAlt(true)
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (shown !== 'story') return
      if (level !== 'frames' && !((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z')) return
      const t = phStore.get()
      const mod = e.metaKey || e.ctrlKey
      const k = e.key.toLowerCase()
      const playing = transportStore.get().playing
      const rate = transportStore.get().rate
      let handled = true

      if (mod && k === 'z') undoRedo(e.shiftKey)
      else if ((mod && k === 'k') || (k === 'b' && !mod)) cut()
      else if (e.code === 'Space') { timelineOwns(); if (playing) transport.stop(); else { snapStore.set(null); transport.play(1) } }
      else if (k === 'l' && !mod) { timelineOwns(); snapStore.set(null); transport.play(playing && rate > 0 ? Math.min(rate * 2, 8) : 1) }
      else if (k === 'j' && !mod) { timelineOwns(); snapStore.set(null); transport.play(playing && rate < 0 ? Math.max(rate * 2, -8) : -1) }
      else if (k === 'k' && !mod) transport.stop()
      else if (k === 'i' && !mod) { setMarks((m) => ({ in: t, out: m.out != null && m.out > t ? m.out : null })); note(`In at ${clock(t)}`) }
      else if (k === 'o' && !mod) { setMarks((m) => ({ in: m.in != null && m.in < t ? m.in : null, out: t })); note(`Out at ${clock(t)}`) }
      else if (k === 'x' && e.altKey) { setMarks({ in: null, out: null }); note('Marks cleared') }
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const dir = e.key === 'ArrowRight' ? 1 : -1
        if (playing) transport.stop()
        if (e.altKey) {
          const g = step(tlRef.current.targets, t, dir)
          if (g) goTo(g.t, { target: g, snapped: true })
        } else goTo(t + dir * (e.shiftKey ? 1 : fr))
      } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        if (playing) transport.stop()
        const g = step(tlRef.current.targets, t, e.key === 'ArrowDown' ? 1 : -1, 'shot')
        if (g) goTo(g.t, { target: g, snapped: true })
      } else if (k === 'q' && !mod) trimToPlayhead('in', e.altKey)
      else if (k === 'w' && !mod) trimToPlayhead('out', e.altKey)
      else if (e.key === ',' || e.key === '.' || e.key === '<' || e.key === '>' || e.code === 'Comma' || e.code === 'Period') {
        const units = e.code === 'Comma' || e.key === ',' || e.key === '<' ? -1 : 1
        trimBy(units, mod ? 'beat' : e.shiftKey ? 'second' : 'frame')
      } else if (e.key === 'Delete' || e.key === 'Backspace') deleteSelection(e.altKey)
      else if (e.key === '?') setHelp((h) => !h)
      else if (e.key === 'Escape') { setHelp(false); setSelected(null); setSelAudio(null); setSelJoin(null) }
      else handled = false
      if (handled) e.preventDefault()
    }
    const up = (e: KeyboardEvent) => { if (e.key === 'Alt') setAlt(false) }
    const blur = () => setAlt(false)
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', blur)
    }
  })

  // ---- direct timeline edits ----------------------------------------------------
  const reorder = (key: string, to: number) => {
    const items = tl.items
    const from = items.findIndex((x) => x.key === key)
    if (from < 0 || to === from || to === from + 1) return
    const rest = items.filter((x) => x.key !== key)
    const target = rest[to > from ? to - 1 : to]
    run([target ? { op: 'move_shot', shot: key, beat: target.beat_id, before: target.key }
      : { op: 'move_shot', shot: key, beat: rest.at(-1)?.beat_id ?? null }], 'You moved a shot on the timeline')
  }
  const insertShot = (shotId: string, at: number) => {
    const items = tl.items
    const onBoard = items.find((i) => i.key === shotId)
    if (onBoard) { reorder(onBoard.key, at); return }
    const target = items[at]
    run([target ? { op: 'add_shot', shot: shotId, beat: target.beat_id, before: target.key }
      : { op: 'add_shot', shot: shotId, beat: items.at(-1)?.beat_id ?? null }], 'You added a shot from the shelf')
  }
  const beatById = (id: string) => session?.board?.beats.find((b) => b.id === id)
  const beatIndex = (id: string) => session?.board?.beats.findIndex((b) => b.id === id) ?? -1
  const beatAction = (action: 'play' | 'up' | 'down' | 'remove' | 'frames', id: string) => {
    const b = beatById(id)
    if (!b) return
    const i = beatIndex(id)
    if (action === 'play') {
      const span = spanOf(b.shots.map((x) => x.key))
      if (span) playEdit(span[0], span[1])
      else playSource(`beat:${id}`, b.shots.filter((x) => !x.gap && x.clip_id).map((x) => ({ id: x.id, clipId: x.clip_id!, start: x.start, end: x.end })))
    } else if (action === 'up') run([{ op: 'move_beat', beat: id, to_index: i - 1 }], `You moved “${b.title}” up`)
    else if (action === 'down') run([{ op: 'move_beat', beat: id, to_index: i + 1 }], `You moved “${b.title}” down`)
    else if (action === 'remove') { setStorySel(null); run([{ op: 'drop_beat', beat: id }], `You removed “${b.title}”`) }
    else if (action === 'frames') {
      stopQueue()
      setSegment(null)
      setLevel('frames')
      const first = tl.items.find((it) => it.beat_id === id)
      if (first) setTimeout(() => { transport.seek(first.seq_start); snapStore.set(null) }, 50)
    }
  }
  const moveBeat = (id: string, to: number) => run([{ op: 'move_beat', beat: id, to_index: to }], `You moved “${beatById(id)?.title}”`)
  const retitle = (id: string, title: string) => run([{ op: 'retitle_beat', beat: id, title }], `You renamed “${beatById(id)?.title}”`)
  const entry = (key: string) => session?.board?.beats.flatMap((b) => b.shots).find((x) => x.key === key)
  const doSwap = (key: string, withShot: string | null) =>
    run([{ op: 'swap_shot', shot: key, with_shot: withShot }], withShot ? 'You swapped a shot' : 'You asked for a better shot')

  const menuItems = (): { title: string; items: MenuItem[] } => {
    if (!menu) return { title: '', items: [] }
    const e = entry(menu.key)
    const it = tl.items.find((x) => x.key === menu.key)
    if (menu.kind === 'gap') {
      return { title: `Empty space · ${it ? (it.seq_end - it.seq_start).toFixed(1) : '?'}s`, items: [
        { label: 'Close up this empty space', onClick: () => run([{ op: 'drop_shot', shot: menu.key }], 'You closed up an empty space') },
        { label: 'Keep it', onClick: () => {} },
      ] }
    }
    const openSwap = () => e && setSwap({ key: menu.key, thumb: e.thumb, id: e.id })
    if (menu.kind === 'story-shot') {
      return { title: `This shot · ${e ? (e.end - e.start).toFixed(1) : '?'}s`, items: [
        { label: 'Watch this shot', onClick: () => {
          const span = spanOf([menu.key])
          if (span) playEdit(span[0], span[1])
          else if (e?.clip_id) preview(e.clip_id, e.start, e.end, e.id)
        } },
        { label: 'Swap for a different shot…', onClick: openSwap },
        { label: 'Remove from the story', danger: true, onClick: () => run([{ op: 'drop_shot', shot: menu.key }], 'You removed a shot') },
      ] }
    }
    const t = phStore.get()
    return { title: `Shot ${it?.n ?? ''} · at ${clock(t)}`, items: [
      { label: 'Play from here', onClick: () => { timelineOwns(); transport.play(1) } },
      { label: 'Cut the shot in two here', hint: 'B', onClick: () => cutAt(t) },
      { label: 'Start the shot here', hint: 'Q', onClick: () => trimToPlayhead('in', false) },
      { label: 'End the shot here', hint: 'W', onClick: () => trimToPlayhead('out', false) },
      { label: 'Swap for a different shot…', onClick: openSwap },
      tl.audio?.off.includes(menu.key)
        ? { label: 'Its sound is on its own strip below', disabled: true, onClick: () => {} }
        : { label: 'Take the sound off (extract audio)', onClick: () => run([{ op: 'extract_audio', shot: menu.key }], `You took the sound off shot ${it?.n}`) },
      { label: 'Remove — the rest moves up', hint: 'Delete', danger: true, onClick: () => run([{ op: 'drop_shot', shot: menu.key }], `You removed shot ${it?.n}`) },
      { label: 'Remove — leave empty space', hint: '⌥ Delete', danger: true, onClick: () => run([{ op: 'drop_shot', shot: menu.key, leave_gap: true }], `You removed shot ${it?.n}, leaving the space`) },
    ] }
  }
  // ---- words on screen ------------------------------------------------------
  const runOverlay = async (ops: Record<string, unknown>[], label: string) => {
    const before = new Set(ovData.items.map((o) => o.id))
    const s = await run(ops, label)
    const added = s?.overlays.items.find((o) => !before.has(o.id))
    if (added) { setSelOverlay(added.id); showOverlay(added) }
    return s
  }
  const showOverlay = (o: Overlay) => {
    const t = phStore.get()
    if (t < o.start || t >= o.shown_end) transport.seek(Math.min(o.start + 0.6, (o.start + o.shown_end) / 2))
  }
  const watchOverlay = (o: Overlay) => {
    stopQueue()
    setSegment(null)
    transport.seek(Math.max(0, o.start - 0.8))
    transport.play(1)
  }
  const suggestOverlays = async () => {
    const { profile } = loadProfile(window.localStorage)
    const said = session?.proposals?.direction?.trim()
    const s = await api.suggestOverlays({ profile, title: said && said.length <= 48 ? said : undefined })
    setSession(s)
    offerUndo(s)
  }
  const newOverlayAt = (kind: OverlayKind): Record<string, unknown> => {
    const { profile } = loadProfile(window.localStorage)
    const items = tl.items
    const beatId = level === 'story' && storySel ? storySel.beat : null
    const it = level === 'frames' ? items[locate(items, phStore.get())]
      : beatId ? items.find((x) => x.beat_id === beatId) : items[0]
    const where = kind === 'end' || kind === 'chapters' ? {}
      : level === 'frames' ? { start: r3(phStore.get()) }
        : beatId ? { beat: beatId, at: 0.3 } : { start: 0.4 }
    const partNo = it ? parts.findIndex((p) => p.id === it.beat_id) + 1 : 1
    const clip = it?.clip_id ? clips.find((c) => c.id === it.clip_id) : null
    const handle = profile.handle.trim() ? (profile.handle.startsWith('@') ? profile.handle : '@' + profile.handle.trim()) : ''
    const words: Record<OverlayKind, Record<string, unknown>> = {
      title: { text: session?.board?.name ?? 'Title' },
      part: { text: it?.beat_title ?? 'Part', sub: `Part ${partNo}` },
      name: { text: profile.name.trim() || 'Name', sub: handle },
      caption: { text: 'What you said here' },
      date: { text: shortDate(clip?.capture_time) ?? shortDate(new Date().toISOString())! },
      end: { text: 'Thanks for watching', sub: handle },
      chapters: {},
      heading: { text: it?.beat_title ?? 'Chapter', sub: 'what happens here', look: 'spaced' },
    }
    return { ...where, ...words[kind] }
  }
  const editOverlayOnTimeline = (id: string, patch: { start?: number; dur?: number }) => {
    const o = ovData.items.find((x) => x.id === id)
    const what = patch.start != null ? 'moved' : 'changed the length of'
    run([{ op: 'edit_overlay', overlay: id, ...patch }], `You ${what} the ${o ? KIND_META[o.kind].label.toLowerCase() : 'overlay'}`)
  }
  const selectOverlay = (id: string | null) => {
    setSelOverlay(id)
    if (id) { setSelected(null); setSelAudio(null); setSelJoin(null); setInsTab('captions') }   // its Style and Animation are in the inspector
    const o = id ? ovData.items.find((x) => x.id === id) : null
    if (o && level === 'frames') { timelineOwns(); showOverlay(o) }
  }
  // Words dragged on the picture: one undoable edit per drop.
  const overlayEdit: OverlayEdit | undefined = session?.board ? {
    selected: selOverlay,
    onSelect: (id) => { setSelOverlay(id); if (id) { setSelected(null); setSelAudio(null); setSelJoin(null); setInsTab('captions') } },
    onPlace: (id, place) => {
      const o = ovData.items.find((x) => x.id === id)
      const name = o ? KIND_META[o.kind].label.toLowerCase() : 'words'
      run([{ op: 'edit_overlay', overlay: id, place }], place ? `You moved the ${name}` : `You put the ${name} back in its usual place`)
    },
    onPlaceAll: (place) => {
      const ops = ovData.items.filter((o) => o.kind === 'caption').map((o) => ({ op: 'edit_overlay', overlay: o.id, place }))
      if (ops.length) run(ops, 'You put every caption in the same place')
    },
    onOpen: (id) => selectOverlay(id),
    onWords: (id, patch) => {
      const o = ovData.items.find((x) => x.id === id)
      run([{ op: 'edit_overlay', overlay: id, ...patch }], `You changed the words of the ${o ? KIND_META[o.kind].label.toLowerCase() : 'caption'}`)
    },
  } : undefined
  const overlaysPanel = session?.board ? (
    <Overlays data={ovData} items={tl.items} level={level} selected={selOverlay} busy={!!pending}
              onSelect={selectOverlay} onRun={runOverlay} onSuggest={suggestOverlays} onWatch={watchOverlay} newAt={newOverlayAt} />
  ) : null
  const applyTalk = async (captions: boolean) => {
    const { profile } = loadProfile(window.localStorage)
    const s = await api.talkApply(captions, profile)
    setSession(s)
    offerUndo(s)
    setTalkOpen(false)
    setPeek(null)
  }
  const openTalk = () => { transport.stop(); stopQueue(); setMenu(null); setLevel('story'); setTalkOpen(true) }
  const openExport = () => { transport.stop(); videoRef.current?.pause(); stopQueue(); setMenu(null); setExporting(true) }
  const openRemix = () => { transport.stop(); videoRef.current?.pause(); stopQueue(); setMenu(null); setReferencing(false); setRemixing(true) }
  const remixDone = async () => { await refresh(); setPeek(null); setWatching(true); setLevel('frames') }
  const startOver = async () => {
    setRestart(false)
    try { await api.clear(); await refresh(); setLocal([hello]); setPeek(null); setLevel('story') }
    catch (e) { note((e as Error).message) }
  }
  const rename = async (name: string) => {
    setRenaming(false)
    if (!name.trim() || name.trim() === session?.project?.name) return
    try { await api.renameProject(id, name.trim()); setSession(await api.session()) } catch (e) { note((e as Error).message) }
  }

  const usedIds = useMemo(() => new Set((session?.board?.beats ?? []).flatMap((b) => b.shots.map((x) => x.id))), [session])
  const apply = async (o: Option) => {
    await run([{ op: 'choose_option', option: o.key }], `You started from “${o.name}”`)
    setOthersOpen(false)
    setLevel('frames')
  }
  // No story choice for now (sarah, 2026-10-07: "jump immediately into
  // frames"): the story the shoot suggests (tempo.pick_story) is taken and
  // the edit opens in Frames. The others stay under Story.
  const autoChosen = useRef(false)
  const props = session?.proposals
  const firstOption = !session?.board && !pending && props
    ? props.options.find((o) => o.key === props.recommended) ?? props.options[0] : undefined
  useEffect(() => {
    if (firstOption && !autoChosen.current) { autoChosen.current = true; apply(firstOption).finally(() => { autoChosen.current = false }) }
  }, [firstOption?.key]) // eslint-disable-line react-hooks/exhaustive-deps
  const clear = () => session?.board && run(session.board.beats.map((b) => ({ op: 'drop_beat', beat: b.id })),
    'You cleared the timeline')

  const marksOf = useMemo(() => {
    const d = session?.last?.diff && !session.last.diff.replaced ? session.last.diff : null
    const m: Record<string, 'added' | 'moved' | 'trimmed' | undefined> = {}
    d?.shots.added.forEach((x) => { m[x.id] = 'added' })
    d?.shots.moved.forEach((x) => { m[x.id] ??= 'moved' })
    d?.shots.trimmed.forEach((x) => { m[x.id] ??= 'trimmed' })
    return m
  }, [session])

  const label = queue && segment
    ? (() => {
      const c = clips.find((x) => x.id === segment.clipId)
      return `${queue.source === 'board' ? 'Storyboard' : 'Preview'} ${queue.index + 1}/${queue.items.length} · ${c?.name ?? ''} · ${clock(segment.start)}–${clock(segment.end)}`
    })()
    : segment ? clips.find((x) => x.id === segment.clipId)?.name ?? '' : tl.items.length ? 'Timeline' : ''
  const storyLabel = queue
    ? `${queue.source === 'board' ? 'Your story'
      : queue.source.startsWith('card:') ? `“${session?.proposals?.options.find((o) => `card:${o.key}` === queue.source)?.name ?? 'Option'}”`
        : queue.source.startsWith('beat:') ? `“${beatById(queue.source.slice(5))?.title ?? 'This part'}”` : 'Preview'} — shot ${queue.index + 1} of ${queue.items.length}`
    : segment ? (clips.find((x) => x.id === segment.clipId)?.name ?? 'One shot') : 'Nothing playing'

  // ---- screens -------------------------------------------------------------
  if (opened !== 'ok') {
    return (
      <div className="grid h-full place-items-center bg-ink p-6">
        {opened === 'loading' ? <p className="text-[13px] text-muted">Opening…</p> : (
          <div className="max-w-md text-center">
            <h2 className="font-serif text-[24px] text-zinc-100">This video couldn’t be opened</h2>
            <p className="mt-2 text-[13px] text-zinc-400">{opened}</p>
            <Button variant="primary" className="mt-4" onClick={() => go({ kind: 'projects' })}>Back to your videos</Button>
          </div>
        )}
      </div>
    )
  }

  const fmt = brief?.style?.format ?? (tl.frame && tl.frame.w > tl.frame.h ? 'wide' : 'tall')
  const FRAMES: FrameChoice[] = [
    { key: 'short', name: 'Short', ratio: '9:16', about: 'Reels, TikTok, Shorts', wide: false },
    { key: 'tall', name: 'Vlog', ratio: '9:16', about: 'Upright, any length', wide: false },
    { key: 'wide', name: 'Wide', ratio: '16:9', about: 'YouTube, a laptop or TV', wide: true },
  ]
  const pickFrame = async (key: string) => {
    const f = FRAMES.find((x) => x.key === key)
    try { setSession(await api.format(key)); note(`The video is now ${f?.name.toLowerCase()} · ${f?.ratio}`) } catch (e) { note((e as Error).message) }
  }
  const player = (big: boolean) => (
    <Player videoRef={videoRef} backRef={backRef} veilRef={veilRef} bars={session?.mix?.bars} segment={segment}
            label={big ? label : tr.playing && !segment ? 'Your story, with its captions — click to pause' : storyLabel}
            gap={tr.gap && !segment} overlay={overlayView} frame={tl.frame} overlayEdit={overlayEdit}
            onTime={() => {}} onEnd={() => { if (queue) playAt(queue, queue.index + 1) }} onPlayingChange={() => {}}
            dark={big}
            controls={big ? (
              <PreviewBar total={tl.total} clip={segment ? (clips.find((c) => c.id === segment.clipId)?.name ?? 'from Media') : null}
                          onPlay={() => {
                            timelineOwns()
                            if (transportStore.get().playing) { transport.stop(); return }
                            if (phStore.get() >= tl.total - 0.05) transport.seek(0)
                            snapStore.set(null)
                            transport.play(1)
                          }}
                          onBack={() => { videoRef.current?.pause(); timelineOwns(); transport.seek(phStore.get()) }}
                          frames={FRAMES} frame={fmt} onFrame={pickFrame}
                          onFull={() => { stageRef.current?.requestFullscreen?.().catch(() => {}) }} />
            ) : undefined} />
  )
  const selItem = selected ? tl.items.find((x) => x.key === selected) ?? null : null
  // Chat on pause: only while the edit is stopped on a frame, about that frame.
  const pauseChat = session?.board && !tr.playing && !segment
    ? <PauseChat busy={!!pending} onApply={(ops, label) => run(ops, label)} items={tl.items}
                 clipName={(id) => clips.find((c) => c.id === id)?.name ?? id}
                 who={chatWho} aiSwitch={<AISwitch ai={ai} onToggle={toggleAI} />} aiKey={!!ai?.available}
                 onAnswered={() => { api.session().then(setSession, () => {}) }} />
    : null
  const chat = (
    <Chat items={chatItems} pending={pending} onSend={(text, extra) => send(text, undefined, extra)}
          onStop={stopChat} onToggle={toggle}
          onCheck={session?.board ? checkEdit : undefined} pendingLine={checking ? 'Looking over every shot of your cut…' : undefined}
          disabled={!!pending} who={chatWho} turnsKey={turnsKey} spent={session?.ai_spent ?? 0}
          aiSwitch={chatWho ? undefined : <AISwitch ai={ai} onToggle={toggleAI} />} aiKey={!!ai?.available}
          hasBoard={!!session?.board || !!session?.proposals}
          timeline={session?.board ? tl.items : undefined} paused={!tr.playing && !segment} selected={selItem}
          prefs={session?.preferences ?? null} onClassify={classify} onRule={changeRule}
          onSuggest={async (r) => { const s = await api.suggest(r); setSession(s) }}
          review={session?.last ? { turn: session.last.turn, items: session.last.review ?? [] } : null} />
  )

  // ---- the edit screen's pieces ------------------------------------------------
  const toggleCaptions = async () => {
    try { const r = await api.captions(!ovData.items.length); setSession(r); offerUndo(r) }
    catch (e) { note((e as Error).message) }
  }
  const looking = session?.bed?.stage === 'looking'
  const musicNode = session?.board ? (
    <div className="space-y-3">
      <p className="font-serif text-[16px] leading-snug text-zinc-100">
        {looking ? `Finding a song${session.bed?.source ? ` from ${session.bed.source}` : ''}…${session.bed?.total ? ` ${session.bed.done}/${session.bed.total}` : ''}`
          : session.music ? <>Playing under the video: <b className="font-medium">{session.music.title}</b></> : 'No music under this video.'}
      </p>
      {!session.music && !looking && session.bed?.why && <p className="font-serif text-[15px] leading-snug text-zinc-300">{session.bed.why}</p>}
      <Button variant={session.music ? 'secondary' : 'primary'} disabled={looking}
              title={session.music ? 'Take the music out' : 'Find a free song that fits this edit and put the cuts on its beat'}
              onClick={async () => {
                try { const r = await api.bed(!session.music); setSession(r); if (session.music) offerUndo(r) }
                catch (e) { note((e as Error).message) }
              }}>
        {session.music ? 'Take the music out' : 'Find a song for it'}
      </Button>
    </div>
  ) : null
  const selStrip = selAudio ? tl.audio?.strips.find((x) => x.id === selAudio) ?? null : null
  const allJoins = session?.mix?.joins ?? []
  const pickedJoin = selJoin ? allJoins.find((j) => j.after === selJoin) : undefined
  const joinAt = (j: (typeof allJoins)[number]): JoinPick => {
    const k = tl.items.findIndex((x) => x.key === j.after)
    const a = tl.items[k], b = tl.items[k + 1]
    return { join: j, before: a?.n ?? null, after: b?.n ?? null, from: shotThumb(a), to: shotThumb(b) }
  }
  const ovSel = selOverlay ? ovData.items.find((o) => o.id === selOverlay) : undefined
  const capSel = selOverlay ? ovData.items.find((o) => o.id === selOverlay && o.kind === 'caption') : undefined
  const capFirst = capSel ?? ovData.items.find((o) => o.kind === 'caption')
  const capUnder = capFirst ? tl.items[locate(tl.items, Math.min(capFirst.start + 0.1, tl.total - 1e-3))] : tl.items[0]
  const capText = capFirst?.text ?? 'Coffee run'
  // with no shot clicked the Effects tab shows every shot's effect, if they all share one
  const shotItems = tl.items.filter((x) => x.kind === 'shot')
  const same = shotItems.length > 0 && shotItems.every((x) => (x.effect ?? null) === (shotItems[0].effect ?? null)
    && (x.effect_amount ?? 1) === (shotItems[0].effect_amount ?? 1))
  const allEffect = { effect: same ? shotItems[0].effect ?? null : null, amount: same ? shotItems[0].effect_amount ?? 1 : 1,
                      thumb: shotThumb(shotItems[0]) }
  const inspector = (
    <Inspector tab={insTab} onTab={setInsTab}
               item={selItem} itemThumb={shotThumb(selItem ?? undefined)}
               clipName={selItem?.clip_id ? clips.find((c) => c.id === selItem.clip_id)?.name ?? '' : ''}
               extracted={!!selItem && !!tl.audio?.off.includes(selItem.key)}
               strip={selStrip}
               join={pickedJoin ? joinAt(pickedJoin) : allJoins[0] ? joinAt(allJoins[0]) : null} joinPicked={!!pickedJoin}
               style={ovData.style} captionsOn={!!ovData.items.length} captionThumb={shotThumb(capUnder)}
               captionSample={capText.length > 20 ? capText.slice(0, Math.max(10, capText.lastIndexOf(' ', 20))) : capText}
               caption={ovSel ?? null}
               onCaptionEdit={(patch, label) => ovSel && run([{ op: 'edit_overlay', overlay: ovSel.id, ...patch }], label)}
               onCaptionDelete={() => { if (ovSel) { run([{ op: 'drop_overlay', overlay: ovSel.id }], `You removed the ${KIND_META[ovSel.kind].label.toLowerCase()}`); setSelOverlay(null) } }}
               onCaptionAdd={() => runOverlay([{ op: 'add_overlay', kind: 'caption', ...newOverlayAt('caption') }], 'You added a caption')}
               onCaptionWatch={() => ovSel && watchOverlay(ovSel)}
               onCaptionDone={() => setSelOverlay(null)}
               onCaptionPlace={(place, label) => ovSel && run([{ op: 'edit_overlay', overlay: ovSel.id, place }], label)}
               looks={ovData.look ? { id: ovData.look.id, all: ovData.look.all } : null}
               music={musicNode}
               video={session?.board ? (
                 <div className="space-y-2">
                   <LengthButton wide total={tl.total} onDone={(r) => { setSession(r); offerUndo(r); note(r.length_note) }} />
                   <PaceButton wide pace={brief?.style?.pace} why={brief?.tempo}
                               story={session.board?.option === session.proposals?.recommended ? session.proposals?.why : undefined}
                               onDone={(r) => { setSession(r); offerUndo(r) }} />
                   <SmoothButton wide rough={(session.seams ?? []).filter((x) => x.verdict !== 'ok').length}
                                 onSmooth={async (order, nudge) => { const r = await api.smooth(order, nudge); setSession(r); offerUndo(r) }} />
                   <CutNotes turn={session.last?.turn ?? null} onJump={(n) => {
                     // a cut plays through from just before it; a caption shows from its start
                     timelineOwns(); snapStore.set(null)
                     transport.seek(Math.max(0, n.kind === 'cut' ? n.t - 1.5 : n.t + 0.3))
                     if (n.kind === 'cut') transport.play(1)
                   }} />
                 </div>
               ) : null}
               onFix={(patch, label) => selItem && run([{ op: 'set_shot', shot: selItem.key, ...patch }], label)}
               onTrim={(edge, to) => {
                 if (!selItem) return
                 const longer = edge === 'out' ? to > selItem.src_end : to < selItem.src_start
                 run([{ op: 'trim', shot: selItem.key, edge, to: r3(to) }],
                   `You made shot ${selItem.n ?? ''} ${longer ? 'longer' : 'shorter'} at the ${edge === 'in' ? 'start' : 'end'}`)
               }}
               onSplit={() => {
                 if (!selItem) return
                 const t = phStore.get()
                 cutAt(t > selItem.seq_start + fr && t < selItem.seq_end - fr ? t : (selItem.seq_start + selItem.seq_end) / 2)
               }}
               onSwap={() => { const e = selItem && entry(selItem.key); if (selItem && e) setSwap({ key: selItem.key, thumb: e.thumb, id: e.id }) }}
               onDelete={() => { if (!selItem) return; run([{ op: 'drop_shot', shot: selItem.key }], `You removed shot ${selItem.n}`); setSelected(null) }}
               onCloseGap={() => { if (!selItem) return; run([{ op: 'drop_shot', shot: selItem.key }], 'You closed up an empty space'); setSelected(null) }}
               onExtract={() => selItem && run([{ op: 'extract_audio', shot: selItem.key }], `You took the sound off shot ${selItem.n}`)}
               onStrip={(patch, label) => selStrip && run([{ op: 'edit_audio', audio: selStrip.id, ...patch }], label)}
               onStripDelete={() => { if (!selStrip) return; run([{ op: 'drop_audio', audio: selStrip.id }], `You deleted the sound of shot ${selStrip.n ?? ''}`); setSelAudio(null) }}
               onCaptions={toggleCaptions}
               onCaptionStyle={(patch, label) => run([{ op: 'overlay_style', ...patch }], label)}
               onJoin={(op, label) => run([{ op: 'set_transition', ...(op.all || !pickedJoin ? {} : { shot: pickedJoin.after }), ...op }], label)}
               onLook={(id, name) => run([{ op: 'set_look', look: id }], `The video now has the ${name} look`)}
               allEffect={allEffect}
               onEffect={(patch, all, label) => {
                 const keys = all ? tl.items.filter((x) => x.kind === 'shot').map((x) => x.key) : selItem ? [selItem.key] : []
                 if (keys.length) run(keys.map((k) => ({ op: 'set_shot', shot: k, ...patch })), label)
               }} />
  )
  const RAIL: { id: NonNullable<typeof side>; icon: IconName; label: string }[] = [
    { id: 'media', icon: 'media', label: 'Media' },
    { id: 'text', icon: 'text', label: 'Text' },
    { id: 'music', icon: 'music', label: 'Music' },
    // the chat is the AI's way in; with the AI off it still holds every change, each with its Undo
    { id: 'chat', icon: chatWho ? 'spark' : 'history', label: chatWho ? 'AI Edit' : 'History' },
  ]
  const panelHead = (title: string, extra?: React.ReactNode) => (
    <header className="flex h-14 shrink-0 items-center gap-2 px-4">
      <span className="font-serif text-[19px] text-zinc-100">{title}</span>
      <div className="flex-1" />
      {extra}
    </header>
  )
  const sidePanel = side === 'media' ? (
    <Shelf clips={clips} inEdit={inEdit} busy={!!importing}
           onPick={(fl) => importPicked(fromInput(fl))}
           onPreview={(c) => {
             // what the video uses of it, else its first shot
             const it = tl.items.find((x) => x.clip_id === c.id && x.shot_id)
             const sh = c.shots[0]
             if (it) preview(c.id, it.src_start, it.src_end, it.shot_id!)
             else if (sh) preview(c.id, sh.start, sh.end, sh.id)
           }}
           onMove={async (c, into) => {
             try {
               const r = await api.pile(c.id, into)
               setSession(r); offerUndo(r)
               setClips((await api.project()).clips) // the rough cut's call moved with it
             } catch (e) { note((e as Error).message) }
           }} />
  ) : side === 'text' ? <>
    {panelHead('Text', <Button size="sm" aria-pressed={!!ovData.items.length} onClick={toggleCaptions}>{ovData.items.length ? 'Turn captions off' : 'Turn captions on'}</Button>)}
    <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">{overlaysPanel}</div>
  </> : side === 'music' ? <>
    {panelHead('Music')}
    <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 pb-4">
      {musicNode}
      {session?.board && <Music board={session.board} inUse={session.music?.id ?? null} onSession={setSession} />}
    </div>
  </> : side === 'chat' ? <>
    <div className="flex min-h-0 flex-1 flex-col [&>aside]:min-h-0 [&>aside]:flex-1 [&>aside]:border-r-0">{chat}</div>
  </> : null
  const card = 'flex min-h-0 shrink-0 flex-col overflow-hidden rounded-2xl border border-line bg-panel'

  const centre = talkOpen && caps.speech
    ? <TalkCut onApply={applyTalk} onWatch={preview} onClose={() => setTalkOpen(false)} />
    : screen === 'footage' ? (
      <Footage clips={clips} importing={importing} errors={session?.import_errors ?? []} vision={caps.vision}
               onPick={(fl) => importPicked(fromInput(fl))} onRetry={retryImport}
               onDecide={(c, a) => { cutOverride(c.id, a).catch((e) => note((e as Error).message)) }}
               canContinue={!!clips.length && !importing && stage !== 'footage'} briefDone={!!brief}
               onNext={() => { showStep(stage === 'story' ? 'story' : brief ? 'cut' : 'brief'); if (!brief) startQuestions() }} />
    ) : screen === 'cut' ? (
      <div className="grid flex-1 place-items-center font-serif text-[17px] text-zinc-200">Trimming your clips…</div>
    ) : (
      <Story
        session={session}
        clips={clips}
        asking={!!pending}
        playing={boardPlay ? 'board' : queue?.source ?? null}
        nowShot={boardPlay ? (boardShot && entry(boardShot)?.id) ?? null : queue ? queue.items[queue.index]?.id ?? null : null}
        selected={storySel}
        onUse={apply}
        onPlay={playSource}
        onSelect={(sel, anchor) => {
          setStorySel(sel)
          if (sel?.kind === 'shot' && anchor) {
            setMenu({ kind: entry(sel.key)?.gap ? 'gap' : 'story-shot', key: sel.key, anchor })
          } else setMenu(null)
        }}
        onMoveBeat={moveBeat}
        onRetitle={retitle}
        onBeatAction={beatAction}
        onReference={() => setReferencing(true)}
        othersOpen={othersOpen}
        onOthersOpen={(o) => { setOthersOpen(o); if (!o) setLevel('frames') }}
        onSmooth={async (order, nudge) => { const s = await api.smooth(order, nudge); setSession(s); offerUndo(s) }}
        onJoin={(after, sound) => run([{ op: 'set_join', shot: after, sound }],
          sound === 'default' ? 'Sound back to automatic' : 'Changed how the sound crosses a cut')}
      />
    )

  const storyStage = shown === 'story' && !talkOpen
  const framesView = storyStage && level === 'frames'
  const cols = framesView ? 'grid-cols-[minmax(0,1fr)]'
    : storyStage ? (narrow ? 'grid-cols-[minmax(0,1fr)]' : 'grid-cols-[320px_minmax(0,1fr)_420px]')
      : narrow || screen === 'footage' ? 'grid-cols-[minmax(0,1fr)]' : 'grid-cols-[minmax(0,1fr)_400px]'

  return (
    <>
    {setup && <Setup data={setup.data} busy={setup.busy} progress={setup.progress} onDone={makeIt} onCancel={() => { if (!setup.busy) setSetup(null) }}
                     ai={ai} estimate={estimate} onAI={toggleAI}
                     onReload={async () => { const d = await api.setup(); setSetup((x) => x && { ...x, data: d }) }} />}
    {asking && <StyleQuestions questions={asking.questions} tailored={asking.tailored}
                               onDone={answered} onCancel={() => setAsking(null)} />}
    <div className="grid h-full grid-rows-[56px_1fr] bg-ink">
      <header className="flex items-center gap-2 border-b border-line bg-ink px-4">
        <button type="button" onClick={() => go({ kind: 'projects' })} title="All your videos" className="flex items-center gap-2 rounded-md px-1 py-0.5 hover:bg-raised">
          <Wordmark />
        </button>
        <span className="mx-2 h-6 w-px shrink-0 bg-line" aria-hidden />
        {renaming ? (
          <input autoFocus defaultValue={session?.project?.name ?? ''} maxLength={80}
                 onBlur={(e) => rename(e.currentTarget.value)}
                 onKeyDown={(e) => { if (e.key === 'Enter') rename(e.currentTarget.value); if (e.key === 'Escape') setRenaming(false) }}
                 className="min-w-0 max-w-[260px] rounded-md border border-accent/60 bg-panel px-2 py-1 font-serif text-[16px] text-zinc-100 outline-none" />
        ) : (
          <div className="relative min-w-0">
            <button type="button" onClick={() => setMore((m) => !m)} aria-haspopup="menu" aria-expanded={more}
                    title="Rename, look at your footage again, and more"
                    className="flex max-w-[280px] items-center gap-1.5 rounded-lg px-2 py-1 font-serif text-[17px] text-zinc-200 hover:bg-raised">
              <span className="truncate">{session?.project?.name ?? '…'}</span><span className="text-[13px] text-zinc-400">▾</span>
            </button>
            {more && (
              <MoreMenu onClose={() => setMore(false)} items={[
                { label: 'Rename this video', onClick: () => setRenaming(true) },
                { label: 'Look at your footage again', hint: 'Every clip, kept and left out', disabled: !framesView, onClick: () => showStep('footage') },
                { label: 'Make my video again…', hint: 'The two picks (and AI, if on), then a fresh edit; Undo brings this one back', disabled: !clips.length || !session?.board, onClick: () => { transport.stop(); startQuestions() } },
                { label: 'Save as my recipe…', hint: 'Cut and dress your next video like this one', disabled: !session?.board, onClick: () => setSavingRecipe(true) },
                { label: 'Other stories…', hint: 'The same clips told another way', disabled: !session?.proposals || !session?.board || shown !== 'story', onClick: () => { transport.stop(); setOthersOpen(true); setLevel('story') } },
                { label: 'Feel like a video you love…', hint: 'Its pace, cuts and colour, never its frames', disabled: !clips.length || shown !== 'story', onClick: () => { transport.stop(); setMenu(null); setReferencing(true) } },
                { label: 'Talking to camera…', hint: caps.speech ? 'Transcribe on this Mac, cut pauses and retakes' : 'Needs macOS 26 with the Xcode command-line tools', disabled: !caps.speech || !clips.length, onClick: openTalk },
                { label: 'Build a short from reference reels…', hint: caps.links ? 'Their pace and length, your clips, free music' : 'Links need yt-dlp; files work', disabled: !clips.length, onClick: openRemix },
                { label: 'All your videos', onClick: () => go({ kind: 'projects' }) },
                { label: 'Start this video over…', hint: 'Clears the footage list and the story; files stay', danger: true, disabled: !clips.length, onClick: () => setRestart(true) },
              ]} />
            )}
          </div>
        )}
        {importing && <span className="hidden truncate font-serif text-[15px] text-accent md:inline" title={importing.text}>reading clips…</span>}

        <div className="flex-1" />
        {!framesView && <Stepper current={shown} derived={stage} done={done} onGo={showStep} compact={narrow} />}
        <div className="flex-1" />

        {narrow && storyStage && !framesView && <Button size="sm" onClick={() => setChatOpen((o) => !o)} aria-pressed={chatOpen}>Chat</Button>}
        <AISwitch ai={ai} onToggle={toggleAI} />
        {session?.board && <>
          <button type="button" onClick={() => undoRedo(false)} disabled={!lastDone} aria-label="Undo" title={lastDone ? `Undo: ${lastDone.lines.map((l) => l.text).join(' · ') || 'the last change'} (⌘Z)` : 'Nothing to undo'}
                  className="grid size-9 place-items-center rounded-lg text-zinc-200 hover:bg-raised disabled:opacity-30"><Icon name="undo" /></button>
          <button type="button" onClick={() => undoRedo(true)} disabled={!lastUndone} aria-label="Redo" title={lastUndone ? 'Redo (⇧⌘Z)' : 'Nothing to redo'}
                  className="grid size-9 place-items-center rounded-lg text-zinc-200 hover:bg-raised disabled:opacity-30"><Icon name="redo" /></button>
          <span className="mx-1 h-6 w-px shrink-0 bg-line" aria-hidden />
          <span className="hidden shrink-0 items-center gap-1.5 font-serif text-[15px] text-zinc-300 md:flex" role="status">
            {isSaving ? 'Saving…' : <><span className="grid size-5 place-items-center rounded-full bg-emerald-400/15 text-emerald-400"><Icon name="check" size={14} /></span>Draft saved</>}
          </span>
        </>}
        <button type="button" title="Your profile" aria-label="Your profile" onClick={() => { transport.stop(); go({ kind: 'profile' }) }}
                className="ml-1 grid size-9 shrink-0 place-items-center rounded-full bg-zinc-700 font-serif text-[15px] font-semibold text-zinc-100 ring-1 ring-zinc-500/40 hover:ring-accent">
          {profileInitial}
        </button>
        <Button variant="primary" disabled={!session?.board} onClick={openExport} className="ml-1 px-4"
                title={session?.board ? 'Render the edit, its captions and its music to one video file' : 'Your edit is still being made'}>
          <Icon name="export" size={18} />Export{session?.exports.length ? ` · ${session.exports.length}` : ''}
        </Button>
      </header>

      <div className={cx('relative grid min-h-0', cols)}>
        {storyStage && !framesView && (narrow ? (chatOpen && (
          <div className="absolute inset-y-0 left-0 z-30 w-[min(360px,90vw)] shadow-2xl shadow-black/60" onKeyDown={(e) => { if (e.key === 'Escape') setChatOpen(false) }}>{chat}</div>
        )) : chat)}

        {framesView && watching ? (
          <main className="relative flex min-h-0 min-w-0 flex-col items-center px-3 pb-3">
            <div ref={stageRef} className="mt-3 flex min-h-0 w-full max-w-[1100px] flex-1 flex-col overflow-hidden rounded-2xl bg-[#121212]">
              {player(true)}
            </div>
            <div className="mt-3 flex w-full max-w-[1100px] flex-wrap items-center justify-center gap-2">
              <button type="button" disabled={session?.bed?.stage === 'looking'}
                      title={session?.music ? 'Take the music out' : 'Find a track that fits and put the cuts on its beat'}
                      onClick={async () => { try { const r = await api.bed(!session?.music); setSession(r); if (session?.music) offerUndo(r) } catch (e) { note((e as Error).message) } }}
                      className="max-w-[18rem] truncate rounded-full border border-line bg-panel px-3 py-1.5 text-[13px] text-zinc-200 hover:bg-raised disabled:opacity-60">
                ♪ {session?.bed?.stage === 'looking' ? 'Finding music…' : session?.music ? session.music.title : 'Music off'}
              </button>
              <LengthButton total={tl.total} onDone={(r) => { setSession(r); offerUndo(r); note(r.length_note) }} />
              <button type="button" title="The look: the words, the colour, how parts join. Click for the next one."
                      onClick={() => {
                        const lk = session?.overlays?.look
                        if (!lk?.all?.length) return
                        const i = lk.all.findIndex((l) => l.id === lk.id)
                        const next = lk.all[(i + 1) % lk.all.length]
                        run([{ op: 'set_look', look: next.id }], `You chose the ${next.name} look`)
                      }}
                      className="rounded-full border border-line bg-panel px-3 py-1.5 text-[13px] text-zinc-200 hover:bg-raised">
                ◐ {session?.overlays?.look?.all?.find((l) => l.id === session?.overlays?.look?.id)?.name ?? 'No look'}
              </button>
              <button type="button" title="Words on the video: a title and a line per stop"
                      onClick={async () => { try { const r = await api.captions(!ovData.items.length); setSession(r); offerUndo(r) } catch (e) { note((e as Error).message) } }}
                      className="rounded-full border border-line bg-panel px-3 py-1.5 text-[13px] text-zinc-200 hover:bg-raised">
                ¶ Words {ovData.items.length ? 'on' : 'off'}
              </button>
              <span className="mx-1 h-6 w-px bg-line" aria-hidden />
              <Button variant="primary" size="md" onClick={() => { transport.stop(); setExporting(true) }}>Download</Button>
              <Button variant="secondary" size="md" onClick={() => setSavingRecipe(true)}
                      title="Cut and dress your next video like this one: it shows up under Cut it like">Save as my recipe</Button>
              <Button variant="ghost" size="md" onClick={() => setWatching(false)} title="The editor: every shot, caption, join and sound">Fine-tune</Button>
            </div>
            {undoable && <p className="mt-2 text-[12px] text-muted">{undoable.text} · <button type="button" className="underline" onClick={() => toggle(undoable.turn)}>Undo</button></p>}
            {session?.habits?.length ? (
              <p className="mt-1 text-[12px] text-muted">
                Kept {session.habits.map((h) => h.text).join(' and ')}, as you did last time ·{' '}
                <button type="button" className="underline" title="Switch this habit off and make the video again without it"
                        onClick={async () => {
                          try {
                            let job = await api.habitSwitch(session.habits![0].id, true, true)
                            while (job.stage && job.stage !== 'done' && job.stage !== 'error') {
                              await new Promise((r) => window.setTimeout(r, 700))
                              job = await api.makeStatus(job.id)
                            }
                            playOnLand.current = true
                            setSession(await api.session())
                          } catch (e) { note((e as Error).message) }
                        }}>Undo that</button>
              </p>
            ) : null}
            {/* this version or that one? her picks teach her taste and tailor this video (PreferCards.tsx) */}
            <PreferCards prefer={session?.prefer ?? null} turns={session?.turns ?? []} onSession={setSession} />
          </main>
        ) : framesView ? (
          <main className="relative flex min-h-0 min-w-0 flex-col px-3 pb-3">
            <div className="relative flex min-h-0 flex-1 pt-3">
              <nav aria-label="Panels" className="flex w-[80px] shrink-0 flex-col gap-1 pr-2">
                {RAIL.map((r) => (
                  <button key={r.id} type="button" aria-pressed={side === r.id} onClick={() => setSide(side === r.id ? null : r.id)}
                          title={side === r.id ? `Close ${r.label}` : r.label}
                          className={cx('flex flex-col items-center gap-1 rounded-xl py-2.5 font-serif text-[15px]',
                            side === r.id ? 'bg-panel text-accent shadow-sm ring-1 ring-line' : 'text-zinc-300 hover:bg-raised hover:text-zinc-100')}>
                    <Icon name={r.icon} size={22} />{r.label}
                  </button>
                ))}
              </nav>
              {side && (
                <div className={cx(card, narrow && 'absolute bottom-0 left-[80px] top-3 z-30 shadow-2xl')} style={{ width: narrow ? Math.min(layout.side, 340) : layout.side }}>
                  {sidePanel}
                </div>
              )}
              {side && !narrow
                ? <Handle axis="x" size={layout.side} onSize={(v, save) => setSize('side', v, save)}
                          max={() => window.innerWidth - layout.inspector - 560} label="Drag to make the left panel wider or narrower" />
                : <div className="w-2 shrink-0" />}
              <div ref={stageRef} className="flex min-h-0 min-w-[280px] flex-1 flex-col overflow-hidden rounded-2xl bg-[#121212]">
                {player(true)}
              </div>
              <Handle axis="x" size={layout.inspector} grow={-1} onSize={(v, save) => setSize('inspector', v, save)}
                      max={() => window.innerWidth - (side && !narrow ? layout.side : 0) - 480} label="Drag to make the right panel wider or narrower" />
              <div className={card} style={{ width: narrow ? Math.min(layout.inspector, 320) : layout.inspector }}>{inspector}</div>
            </div>
            <Handle axis="y" size={layout.timeline} grow={-1} onSize={(v, save) => setSize('timeline', v, save)}
                    max={() => window.innerHeight - 56 - 300} label="Drag to make the timeline taller or shorter" />
            <div className={card}>
              <Timeline tl={tl} marks={marks} marksOf={marksOf} selected={selected} flash={flash} alt={alt} height={layout.timeline}
                        onTrimEdge={(key, edge, to) => {
                          const it = tl.items.find((x) => x.key === key)
                          const longer = edge === 'out' ? to > (it?.src_end ?? to) : to < (it?.src_start ?? to)
                          run([{ op: 'trim', shot: key, edge, to: r3(to) }],
                            `You made shot ${it?.n ?? ''} ${longer ? 'longer' : 'shorter'} at the ${edge === 'in' ? 'start' : 'end'}`)
                        }}
                        onSelect={(key, anchor) => {
                          timelineOwns()
                          setSelected(key)
                          const it = tl.items.find((x) => x.key === key)
                          setSelAudio(null)
                          setSelJoin(null)
                          if (key) { setSelOverlay(null); setInsTab((t) => (t === 'audio' && it?.kind === 'shot' ? t : 'edit')) }
                          // a shot's tools are the inspector; only an empty space gets a menu too
                          if (key && anchor && it?.kind === 'gap') setMenu({ kind: 'gap', key, anchor })
                        }}
                        onReorder={reorder} onInsertShot={insertShot} onClear={clear} onHelp={() => setHelp(true)}
                        onSplit={cut} onDelete={() => deleteSelection(false)}
                        overlays={ovData.items} selectedOverlay={selOverlay} onSelectOverlay={selectOverlay}
                        onOverlayEdit={editOverlayOnTimeline}
                        selectedAudio={selAudio}
                        onSelectAudio={(id) => { timelineOwns(); setSelected(null); setSelJoin(null); setSelAudio(id); setInsTab('audio') }}
                        joins={allJoins} selectedJoin={selJoin}
                        onSelectJoin={(k) => { timelineOwns(); setSelected(null); setSelAudio(null); setSelOverlay(null); setSelJoin(k); setInsTab('effects') }}
                        music={session?.music ?? null}
                        onSelectMusic={() => { setSelected(null); setSelAudio(null); setSelJoin(null); setInsTab('audio') }}
                        onAudioMove={(id, at) => {
                          const a = tl.audio?.strips.find((x) => x.id === id)
                          run([{ op: 'edit_audio', audio: id, at }], `You moved the sound of shot ${a?.n ?? ''} to ${clock(at)}`)
                        }} />
            </div>
            {undoable && <UndoToast text={undoable.text} lift={layout.timeline + 28} onUndo={() => { toggle(undoable.turn); setUndoable(null) }} />}
            {flash && level !== 'frames' && <Flash text={flash} />}
          </main>
        ) : (
          <>
            <main className="relative flex min-h-0 min-w-0 flex-col bg-panel">
              {centre}
              {undoable && <UndoToast text={undoable.text} onUndo={() => { toggle(undoable.turn); setUndoable(null) }} />}
              {flash && <Flash text={flash} />}
            </main>
            {/* Footage has no preview panel (sarah: the stacks use the width, a
                clip plays in place). Hidden, not removed: the player's videos
                stay attached to the transport. */}
            <aside className={cx('flex min-h-0 flex-col gap-3 overflow-y-auto border-line bg-panel p-3',
              narrow ? 'border-t max-h-[46vh]' : 'border-l', screen === 'footage' && 'hidden')}>
              <div className="flex aspect-[16/10] w-full shrink-0 flex-col overflow-hidden rounded-xl border border-line"
                   onClick={() => { if (tr.playing && !segment) transport.stop() }}>
                {player(false)}
              </div>
              {!segment && !tr.playing && !session?.board && <p className="px-1 text-[12px] text-muted">Press Watch on anything to see it here.</p>}
              {pauseChat && <div className="overflow-hidden rounded-xl border border-line">{pauseChat}</div>}
              {storyStage && overlaysPanel}
              {storyStage && session?.board && <Music board={session.board} inUse={session.music?.id ?? null} onSession={setSession} />}
            </aside>
          </>
        )}
      </div>

      {menu && (() => { const m = menuItems(); return <Menu anchor={menu.anchor} title={m.title} items={m.items} onClose={() => setMenu(null)} /> })()}
      {swap && (
        <SwapPicker clips={clips} used={usedIds} current={swap}
                    onPick={(w) => { doSwap(swap.key, w); setSwap(null) }} onClose={() => setSwap(null)} />
      )}
      {session?.music && <audio ref={musicRef} src={session.music.audio} preload="auto" />}
      {session?.mix && <audio ref={mixRef} src={session.mix.audio} preload="auto"
                              onError={() => { transport.mixBroken = true }} />}
      {help && <Keys onClose={() => setHelp(false)} />}
      {exporting && <Export tl={tl} overlays={ovData} parts={parts} music={session?.music?.title ?? null} credit={session?.music?.credit ?? null} style={session?.board?.style}
                            history={session?.exports ?? []} onClose={() => { setExporting(false); api.session().then(setSession).catch(() => {}) }} />}
      {remixing && <Remix onClose={() => { setRemixing(false); setFrontLinks(null) }} onDone={remixDone} canLinks={caps.links}
                          initialLinks={frontLinks ?? ''} autoStart={!!frontLinks} />}
      {referencing && <BorrowStyle onClose={() => setReferencing(false)} onRemix={openRemix}
                                   onApplied={(s) => { setSession(s); offerUndo(s); setReferencing(false); setPeek(null); setLevel('frames') }} />}
      {savingRecipe && <SaveRecipe onClose={() => setSavingRecipe(false)}
                                   onSaved={(r, replaced) => { setSavingRecipe(false); note(`${replaced ? 'Replaced' : 'Saved'} your recipe “${r.name}”. Pick it under Cut it like when you make your next video.`) }} />}
      {restart && <Confirm title="Start this video over?" action="Start over" danger onNo={() => setRestart(false)} onYes={startOver}
                           text="The footage list, the rough trim, the story and its history are cleared. Your clip files and anything you exported are untouched." />}

      {dragging && (
        <div className="pointer-events-none fixed inset-0 z-50 grid place-items-center bg-black/60 backdrop-blur-[2px]">
          <div className="rounded-2xl border-2 border-dashed border-accent px-10 py-8 text-center">
            <div className="text-[18px] font-semibold text-zinc-100">Drop clips or a folder</div>
            <div className="mt-1 text-[12px] text-muted">.mp4 / .mov — added to this video, read on this computer</div>
          </div>
        </div>
      )}
    </div>
    </>
  )
}

// Footage · Edit (sarah 2026-10-07: the style questions, the rough trim and the
// story choice all run on their own). The current one is lit; passed ones
// can be looked at again; the ones ahead say what will happen there.
function Stepper({ current, derived, done, onGo, compact }: {
  current: Stage; derived: Stage; done: Stage[]; onGo: (s: Stage) => void; compact: boolean
}) {
  return (
    <nav aria-label="Steps" className="flex items-center rounded-lg border border-line bg-panel p-0.5">
      {STAGES.filter((s) => s.id === 'footage' || s.id === 'story').map((s, i) => {
        const passed = done.includes(s.id) && s.id !== derived
        const can = done.includes(s.id)
        // the style and trim steps run on their own now: they count as Footage
        const cur = s.id === (current === 'story' ? 'story' : 'footage')
        return (
          <button key={s.id} type="button" disabled={!can} onClick={() => onGo(s.id)} aria-current={cur ? 'step' : undefined}
                  title={s.hint}
                  className={cx('flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] disabled:cursor-default',
                    cur ? 'bg-zinc-700 text-zinc-100' : can ? 'text-zinc-300 hover:bg-raised' : 'text-zinc-600')}>
            <span className={cx('grid size-4 place-items-center rounded-full text-[9px] font-semibold',
              cur ? 'bg-accent text-accent-ink' : passed ? 'bg-emerald-400/20 text-emerald-300' : 'bg-zinc-800 text-zinc-500')}>{passed ? '✓' : i + 1}</span>
            {(!compact || cur) && <span>{s.label}</span>}
          </button>
        )
      })}
    </nav>
  )
}

function MoreMenu({ items, onClose }: { items: { label: string; hint?: string; onClick: () => void; danger?: boolean; disabled?: boolean }[]; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) onClose() }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const t = setTimeout(() => window.addEventListener('mousedown', away), 0)
    window.addEventListener('keydown', esc)
    return () => { clearTimeout(t); window.removeEventListener('mousedown', away); window.removeEventListener('keydown', esc) }
  }, [onClose])
  return (
    <div ref={box} role="menu" className="absolute left-0 top-10 z-40 w-80 rounded-xl border border-line bg-panel p-1.5 shadow-2xl shadow-black/60">
      {items.map((it) => (
        <button key={it.label} type="button" role="menuitem" disabled={it.disabled} onClick={() => { onClose(); it.onClick() }}
                className={cx('block w-full rounded-lg px-3 py-1.5 text-left font-serif text-[16px] disabled:opacity-40',
                  it.danger ? 'text-rose-200 hover:bg-rose-500/10' : 'text-zinc-100 hover:bg-zinc-800')}>
          {it.label}
          {it.hint && <span className="block text-[14px] leading-snug text-zinc-300">{it.hint}</span>}
        </button>
      ))}
    </div>
  )
}

function UndoToast({ text, onUndo, lift }: { text: string; onUndo: () => void; lift?: number }) {
  return (
    // lifted over the timeline, so it never covers a shot
    <div style={lift ? { bottom: lift } : undefined} className="pointer-events-auto absolute bottom-4 left-1/2 z-30 flex max-w-[90%] -translate-x-1/2 items-center gap-3 rounded-xl border border-line bg-zinc-900 px-4 py-2 shadow-2xl shadow-black/60">
      <span className="truncate text-[12px] text-zinc-200">{text}</span>
      <button type="button" onClick={onUndo} className="shrink-0 rounded-md bg-zinc-700 px-2.5 py-1 text-[12px] text-zinc-100 hover:bg-zinc-600">Undo</button>
    </div>
  )
}

// A short note about something that just happened (or couldn't).
function Flash({ text }: { text: string }) {
  return (
    <div role="status" className="pointer-events-none absolute left-1/2 top-3 z-30 max-w-[90%] -translate-x-1/2 truncate rounded-lg border border-line bg-zinc-900/95 px-3 py-1.5 text-[12px] text-zinc-100 shadow-xl">
      {text}
    </div>
  )
}

/** A shot's picture for a tile (the timeline's own thumbnail). */
function shotThumb(it: SeqItem | undefined): string | null {
  if (!it || it.kind !== 'shot' || !it.clip_id || !it.shot_id) return null
  return `/api/thumbs/${it.clip_id}/shot${String(Number(it.shot_id.split(':')[1])).padStart(3, '0')}.jpg`
}
