export type Shot = {
  id: string
  index: number
  start: number
  end: number
  best_t: number
  quality: number
  aesthetic: number | null
  labels: [string, number][]
  faces: number
  utility: boolean | null
  thumb: string
}

export type Clip = {
  id: string
  name: string
  duration: number
  width: number
  height: number
  capture_time: string | null
  gps: [number, number] | null
  sampling: string
  index_seconds: number
  video: string
  shots: Shot[]
  samples?: { times: number[]; base: string }   // ~1 frame a second, for hover previews
  cut: { rejected: boolean; auto_rejected: boolean; zh: string; en: string; override: string | null
         flags: { code: string; zh: string; en: string }[]; windows: Record<string, [number, number]> } | null
}

export type Project = { clips: Clip[]; vision: string; project: ProjectMeta | null }

// One row on the dashboard (backend/projects.py). `stage` is where the
// creator would pick it up: footage · brief · cut · story · exported.
export type ProjectMeta = {
  id: string; name: string; created: number; updated: number
  clips: number; duration: number | null; cover: string | null
  stage: 'footage' | 'brief' | 'cut' | 'story' | 'exported'
  edits: number; exports: number; board: { name: string; parts: number } | null; last_export: ExportRecord | null
}
export type ExportRecord = { job: string; file: string; path: string; at: number; seconds: number; size: { w: number; h: number }
  music: boolean; overlays: number; bytes: number | null
  // launch tracking (backend/launchlog.py): the one question after an export, and what it cost
  verdict?: { post: boolean; note: string; at: number }; elapsed?: number; default_path?: boolean; undone?: number }
export type Brief = { message: string; style: StyleAnswers; said: string; at: number; tempo?: string }
// What this machine can do -- shown, so nothing is offered that then fails.
export type Capabilities = { cloud?: boolean; llm: boolean; speech: boolean; vision: string; links: boolean; music_folder: string | null; platform: string
  chat?: 'openai' | 'claude' | null }
export type ImportError = { path: string | null; error: string }

export type Job = {
  id: string
  known: number
  stage: 'queued' | 'indexing' | 'looking' | 'done' | 'error'
  done: number
  total: number
  errors: { path: string | null; error: string }[]
  vision: string | null
  elapsed: number
}

export type BeatShot = { id: string; clip_id: string; start: number; end: number; thumb: string; lean: boolean; gap?: boolean; why?: string }
export type Beat = { title: string; detail: string; lean: boolean; shots: BeatShot[] }
export type Option = {
  key: 'time' | 'place' | 'subject' | 'voice'
  name: string
  axis: string
  summary: string
  notes: string[]
  degraded: boolean
  same_order_as_time: number | null
  beats: Beat[]
  // the voiceover proposal only
  timing?: 'estimated' | 'text_only'
  gaps?: { line: number; text: string; at: number; dur: number; reason: string }[]
}
export type Proposals = {
  direction: string
  understood: { themes: string[]; used: string[]; ignored: string[]; matched_shots: number }
  notes: string[]
  options: Option[]
  // the story to start from, read from the shoot (tempo.pick_story), and why
  recommended?: string
  why?: string
}

// The working storyboard -- edited by operations, never regenerated.
export type BoardShot = {
  id: string; key: string; clip_id: string | null; start: number; end: number; src_start: number; src_end: number
  thumb: string; lean: boolean; gap?: boolean
}
export type BoardBeat = { id: string; title: string; detail: string; shots: BoardShot[] }
export type Board = { option: string; name: string; structure: string; beats: BoardBeat[]; style?: BoardStyle | null }

// A borrowed style (restyle.py): timing is already in the beats; the rest is rendered at export.
export type TransitionPolicy = { between: string; within: string; dur: number; open: boolean; close: boolean }
export type BoardStyle = {
  ref: string; name: string; traits: string[]; transitions: TransitionPolicy | null
  look: { lut: string; strength: number; words: string[]; pending?: boolean } | null; letterbox: number | null
  report: { shots: number; median_before: number | null; median_after: number | null; target_median: number | null
            filmed_too_short: number; on_beat: number; held_by_voice: number } | null
}
export type RefSummary = { rid: string; title: string; uploader: string | null; url: string | null; downloaded: boolean
  duration: number; learnt_from_s: number; learnt_at: number; summary: string[] }
export type RefJob = { id: string; stage: 'queued' | 'fetching' | 'reading' | 'learning' | 'done' | 'error'; progress: number
  error: string | null; rid: string; elapsed: number; reference: RefSummary | null }
export type RefTrait = { key: 'pace' | 'beat' | 'transitions' | 'look' | 'frame' | 'music'; title: string; words: string[]
  how: string | null; available: boolean; why_not: string | null; on: boolean; evidence: string[]
  numbers?: Record<string, unknown>; counts?: Record<string, number> }
export type RefCard = { reference: RefSummary; traits: RefTrait[]; has_story: boolean; music_folder: boolean
  music: { id: string; title: string; bpm: number | null; score: number; reason: string; audio: string }[] }
export type LookFit = { lut: string; strength: number; previews: { before: string; after: string }[]; look_words: string[]
  numbers: Record<'yours' | 'after' | 'reference', { warmth: number; black: number; sat: number }> }

export type DiffLine = {
  kind: 'removed' | 'added' | 'moved' | 'trimmed' | 'retitled' | 'swapped' | 'replaced' | 'style' | 'sound' | 'none'
  text: string; beat?: string; shot?: string; thumb?: string
}
export type Diff = {
  beats: { removed: { id: string; title: string }[]; added: { id: string }[]; moved: { id: string }[]; retitled: { id: string }[] }
  shots: { removed: { id: string }[]; added: { id: string }[]; moved: { id: string }[]; trimmed: { id: string }[] }
  replaced: boolean
}
export type Turn = {
  id: number; kind: 'chat' | 'direct' | 'check'; text: string; reply: string   // check: the AI checking its own edit
  question: string | null; choices: string[]; lines: DiffLine[]; skipped: string[]
  undone: boolean; at: number; has_ops: boolean; direction: { themes: string[] } | null
  cost?: number | null    // dollars, when an AI answered this turn
  sheets?: string[]       // the contact sheets a check looked at (/api/check/sheet/<name>)
}
import type { SeqItem } from './sequence'
import type { Trans } from './joinView'
import type { Target } from './snap'
export type TimelineData = { fps: number; total: number; items: SeqItem[]; targets: Target[]; grid: { bpm: number; phase: number } | null
  frame?: { w: number; h: number }
  // Sound taken off shots onto its own strips (backend board.extract_audio): where each
  // sits in the edit, its level, and which shots now play silent.
  audio?: { strips: SoundStrip[]; off: string[] } }
export type SoundStrip = { id: string; at: number; dur: number; gain: number; mute: boolean
  clip_id: string; shot: string; src_start: number; n: number | null; fade_in: number; fade_out: number }

// Words on screen. Anchored to the edit, its end, a part or a shot; the
// server resolves each to sequence time (start/end) for drawing.
export type OverlayKind = 'title' | 'part' | 'name' | 'caption' | 'date' | 'end' | 'chapters' | 'heading'
/** a chapter title's own look (overlays.HEADING_LOOKS), independent of the captions' style */
export type HeadingLook = 'script' | 'spaced' | 'bold' | 'serif'
export type OverlayPos = 'top-left' | 'top' | 'top-right' | 'left' | 'center' | 'right' | 'bottom-left' | 'bottom' | 'bottom-right'
export type OverlayAnim = 'fade' | 'rise' | 'slide' | 'type'
export type Overlay = {
  id: string; kind: OverlayKind; text: string; sub: string; pos: OverlayPos; size: 'S' | 'M' | 'L'; anim: OverlayAnim
  dur: number | null; anchor: { to: 'edit' | 'end' | 'beat' | 'shot'; id?: string }; at: number
  start: number; end: number; shown_end: number
  // picked against the picture behind it (backend ink.py): main / accent colour, and a halo when nothing contrasts enough
  ink?: string; ink2?: string; halo?: string
  // dragged on the picture by hand: block centre (0..1 of the frame) and size multiplier
  place?: OverlayPlace | null
  look?: HeadingLook
}
export type OverlayPlace = { x: number; y: number; scale: number }
export type OverlayStyle = { font: 'Clean' | 'Editorial' | 'Rounded' | 'Mono' | 'Condensed'; color: string; accent: string; captions: 'bottom' | 'center'; backing: 'shadow' | 'box' | 'none'
  look?: string; motion?: Motion | null
  /** the caption template and entrance the creator picked (overlays.TEMPLATES / ENTERS); null = the look's own */
  template?: CaptionTemplate | null; enter?: CaptionEnter | null
  /** the captions' colour picked by hand (the Captions tab); null = automatic, read against the footage */
  text_color?: string | null
  /** the captions' font picked by hand (captionFonts.ts id); null = the template's or the look's own */
  typeface?: string | null
  /** set by hand with sliders (overlays.DRESS); null = the template's own, width / opacity 0 = none */
  outline?: CaptionOutline | null; shadow?: CaptionShadow | null; backdrop?: CaptionBackdrop | null; thick?: number | null }
export type CaptionOutline = { color: string; width: number }
export type CaptionShadow = { color: string; opacity: number; blur: number; dist: number }
export type CaptionBackdrop = { color: string; opacity: number; round: number }
export type CaptionTemplate = 'outlined' | 'bold' | 'label' | 'highlight' | 'handwritten' | 'tape' | 'pop' | 'quiet'
  | 'neon' | 'glow' | 'gradient' | 'extrude' | 'retro'
export type CaptionEnter = 'fade' | 'pop' | 'slide' | 'stamp' | 'type' | 'word'
// How a look moves words (backend looks/*.json): one curve and timing for the whole video.
export type Motion = { curve: [number, number, number, number]; in_s: number; step_fps: number; stagger_s: number
  enter: 'card' | 'slam' | null; case: 'sentence' | 'lower' | 'upper'; track: number; beat_lock: boolean
  /** a caption's own entrance, picked in the Animation tab (overlayDraw.motionFor) */
  caption_enter?: CaptionEnter }
export type LookInfo = { id: string; name: string; line: string; font: OverlayStyle['font']; palette: string[]; status: string; review_by: string }
export type OverlayFinding = { overlay: string; rule: string; value: number; verdict: 'ok' | 'warn' | 'bad' | 'pending'; basis: string; message: string }
export type Overlays = { items: Overlay[]; style: OverlayStyle; findings: OverlayFinding[]
  look?: { id: string | null; overrides: string[]; all: LookInfo[] } }
export type MusicTrack = { id: string; title: string; duration: number; bpm: number | null; audio: string; credit?: string | null }
export type Habit = { id: string; kind: 'avoid' | 'prefer' | 'music_off'; label: string | null; weight: number; n: number; evidence: string[]; text: string; used: number; off: boolean }

export type CutSummary = { clips: number; kept: number; rejected: number; raw: number; cut: number; ratio: number | null; line_en: string }
export type Workflow = { state: string; gate: string; decision: string | null; revision: number; history: { action: string; actor: string; note: string; at: number }[] }
export type CutShot = { id: string; full: [number, number]; auto: [number, number]; window: [number, number]; use: [number, number]
  target: number; whole: boolean; reason_zh: string; reason_en: string; notes: string[]; seconds: number[]; override: string | null }
export type CutClip = { id: string; name: string; duration: number; auto_rejected: boolean; rejected: boolean; override: string | null
  code: string; zh: string; en: string; flags: { code: string; zh: string; en: string }[]; talking: boolean; shots: Record<string, CutShot>
  evidence: string[]; unverified: string[] }
export type CutData = { workflow: Workflow; summary: CutSummary | null; clips: CutClip[] }

export type Session = {
  workflow: Workflow
  cut: CutSummary | null
  timeline: TimelineData
  music: MusicTrack | null
  // Music by default (backend/bed.py): the pick runs in the background and lands as a turn.
  // what the creator's habits did to the last Make (habits.py), for the one line and its Undo
  habits?: { id: string; text: string }[]
  // "Which do you like better?" after Make (backend prefer.py): which card of how many, while any are left
  prefer?: { at: number; of: number; deck: number; on: number | null } | null
  bed: { stage: 'looking' | 'done' | 'nothing' | 'error'; why: string; source: string; done: number; total: number; elapsed: number } | null
  // The edit's sound as one track (backend/audiomix.py) -- what preview plays and export writes.
  mix: { key: string; audio: string; joins: JoinInfo[]; transitions: Trans[]; bars: number } | null
  board: Board | null
  structure_note: string | null
  last: { turn: number; diff: Diff | null; ghosts: { index: number; title: string; thumbs: string[] }[]; review: Review[] } | null
  // Every cut, checked (backend cutgrammar/joins.py) -- report only.
  seams: Seam[]
  turns: Turn[]
  proposals: Proposals | null
  llm: boolean
  ai_spent?: number       // dollars AI has cost on this video (chat answers + AI-planned Makes)
  preferences: Preferences
  voiceover: { source: string; timing: 'estimated' | 'text_only'; lines: number; total: number } | null
  overlays: Overlays
  project: ProjectMeta | null
  brief: Brief | null
  exports: ExportRecord[]
  import_errors: ImportError[]
  capabilities: Capabilities
}

export type ExportJob = {
  id: string; stage: 'waiting' | 'shots' | 'joining' | 'finishing' | 'done' | 'error' | 'cancelled'
  done: number; of: number; progress: number; error: string | null; file: string | null; path: string | null
  size: { w: number; h: number }; total: number; overlays: number; music: boolean; elapsed: number
  style?: string | null; notes?: string[]; alt?: boolean   // a version in the other frame
}

// What edits teach -- only once the creator has sorted them.
export type PrefClass = 'long_term' | 'project' | 'single_edit' | 'compliance_fix' | 'rejected'
export type PrefCandidate = {
  turn: number; said: string; kind: 'chat' | 'direct'; lines: string[]; suggested: PrefClass
  readable: boolean; status: 'candidate' | 'confirmed' | 'rejected'; klass: PrefClass | null; rule: string | null
}
export type PrefRule = {
  id: string; klass: 'long_term' | 'project'; rule: string; scope: string; counter: string; reason: string
  active: boolean; evidence: { said: string; changed: string[] }; history: { at: number; action: string; klass: string; actor: string }[]
}
export type PrefSuggestion = { id: string; source: 'undo' | 'verdict'; said: string; rule: string; suggested: PrefClass }
export type Preferences = { candidates: PrefCandidate[]; rules: PrefRule[]; suggestions?: PrefSuggestion[] }

export type TimelineItem = { uid: string; shotId: string; clipId: string; start: number; end: number; thumb: string; beatId: string; beatTitle: string; mark?: Mark }
export type Mark = 'added' | 'moved' | 'trimmed'

export type Msg = { id: string; role: 'user' | 'app'; text: string; busy?: boolean; at: number
  retry?: string }   // a message that didn't go through: Try again sends this

// What the player is showing: one span of one file.
export type Segment = { key: string; clipId: string; start: number; end: number; autoplay: boolean }

// Talking-head mode: the transcript, what would be cut and why.
export type TalkPart = { kind: 'words'; id: string | null; text: string; removed: boolean; code: string | null; zh: string; en: string }
  | { kind: 'pause'; id: string; len: number; cut: boolean }
export type TalkItem =
  | { kind: 'pause'; id: string; len: number; cut: boolean; keeps: number }
  | { kind: 'sentence'; id: string; clip: string; clip_name: string; start: number; end: number; text: string; removed: boolean
      auto: boolean; override: boolean; code: string | null; zh: string; en: string; why: string; flag: string | null
      script_line: number | null; parts: TalkPart[] }
export type TalkPlan = {
  locale: string; source: 'rules' | 'agent'; agent_note: string; clips: { id: string; name: string }[]
  items: TalkItem[]; script: string[]; unsaid: { line: number; text: string }[]
  summary: { raw: number; cut: number; sentences: number; line_en: string
    removed: Record<'pause' | 'retake' | 'stumble' | 'filler' | 'other', { n: number; seconds: number }> }
}
export type TalkJob = { stage: 'transcribing' | 'reviewing' | 'done' | 'error'; done: number; total: number; current: string
  error: string | null; silent: string[] }
export type TalkState = { job: TalkJob | null; plan: TalkPlan | null; llm: boolean }

// The style questions asked once, after the first description (brief.py).
export type StyleChoice = { key: string; label: string; hint?: string; seconds?: number }
// The length slider (brief.length_marks): 15 s up to everything the rough cut kept,
// with Short / Medium / Long marks read from the footage and the kind of video.
export type LengthMark = { key: string; label: string; seconds: number }
export type LengthSlider = { min: number; max: number; marks: LengthMark[]; suggest: string; seconds: number; why: string; kind: string }
export type StyleQuestion = { id: string; question: string; multi: boolean; hint?: string; choices: StyleChoice[]
  slider?: LengthSlider
  /** asked only when an earlier answer is one of these: { captions: ['describe', 'transcribe'] } */
  when?: Record<string, string[]> }
export type StyleAnswers = { length?: string; seconds?: number; pace?: string; opening?: string; captions?: string; caption_look?: string
  format?: 'short' | 'tall' | 'wide'; look?: string }

// How the sound crosses a cut: carried out (L cut), carried in (J cut), or a clean break.
export type JoinSound = 'cut' | 'carry_out' | 'carry_in' | 'default'
export type JoinInfo = { after: string; at: number; sound: Exclude<JoinSound, 'default'>; set: boolean; fits: boolean
  /** the picture at this cut: what plays, and what the creator picked (transitions.py), here or for every cut */
  picture: string; picked: string | null; picked_dur: number | null; picked_all: boolean }

export type SeamFinding = { key: string; label: string; value: number | null; unit: string; verdict: 'ok' | 'warn' | 'bad' | 'pending'; detail: string }
export type Seam = { after: string; before: string; at: number; verdict: 'ok' | 'warn' | 'bad'; findings: SeamFinding[] }
// What a turn did to the cuts: a second look, shown under it.
export type Review = { kind: 'worse' | 'better'; text: string; after?: string; at?: number; verdict?: string }

// A card after Make (backend prefer.py): two versions of the video one change
// apart, each as the shots that play in its window and the sound they play with.
export type PreferSide = { items: SeqItemLike[]; start: number; end: number; audio: string | null; poster: string | null }
export type SeqItemLike = {
  key: string; kind: 'shot' | 'gap'; shot_id: string | null; clip_id: string | null
  src_start: number; src_end: number; seq_start: number; seq_end: number
  beat_id: string; beat_title: string; n: number | null; speed?: number; rotate?: number; fill?: boolean
  mirror?: boolean; punch?: number
}
export type PreferCard = { id: number; ask: string; at: number; of: number; sides: PreferSide[] }
