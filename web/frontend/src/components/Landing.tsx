import { useEffect, useRef, useState, type ReactNode } from 'react'
import { go } from '../router'
import { cx, Wordmark } from '../ui'

// The page that sells the product: what it is, what it can do, how it works,
// what it fixes, what it costs, and the honest limits. 2026-10-23, the user:
// "less words, more straight to the point, and a carousel of animations that
// we can do". So every section says one thing, and the carousel (Moves) plays
// the app's own caption entrances, transitions and effects, by their menu
// names. It lives at #/welcome so the app's own home stays as bare as it is
// (sarah, 2026-10-06).
//
// The look, 2026-10-23, the user: "too cartoon-ish, make it more aesthetic,
// cool and sharp". So it sits on the app's own dark palette (index.css
// .on-video, the one the player uses over footage), with Garamond for what
// people read and the system sans for labels, hairlines instead of cards,
// small corners, film grain, and one accent. No logos, quotes or backers we
// don't have. The copy keeps to the promise in CLAUDE.md: "no amateur tells",
// never "beautiful".

const NAV = [
  ['moves', 'What it can do'],
  ['how', 'How it works'],
  ['pricing', 'Pricing'],
  ['faq', 'FAQ'],
] as const

const display = 'font-serif font-normal tracking-[-0.02em]'
const label = 'text-[11px] font-medium uppercase tracking-[0.16em] text-muted'

// Premium aesthetic colors
const COLORS = {
  accent1: '#FFD93D',      // Bold gold/yellow
  accent2: '#FF6B6B',      // Vibrant coral/red
  accent3: '#4ECDC4',      // Teal
  accent4: '#A78BFA',      // Purple accent for depth
  dark: '#0B0F14',
  card: '#1A1F2E',
  glass: 'rgba(255, 255, 255, 0.05)',
}

export function Landing() {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => { document.title = 'VibeCut — a hundred clips in, one video out' }, [])
  const openApp = () => go({ kind: 'projects' })
  return (
    <div className="lc on-video relative h-full overflow-x-hidden overflow-y-auto scroll-smooth bg-ink font-sans text-zinc-100 antialiased"
         onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 8)}>
      <style>{CSS}</style>
      <div aria-hidden className="lc-glow pointer-events-none absolute inset-x-0 top-0 h-[900px]" />
      <div aria-hidden className="lc-grain pointer-events-none fixed inset-0 z-50" />

      <header className={cx('sticky top-0 z-30 border-b transition-colors', scrolled ? 'border-line bg-ink/80 backdrop-blur-md' : 'border-transparent')}>
        <div className="mx-auto flex h-14 max-w-[1120px] items-center gap-8 px-6">
          <a href="#/welcome" className="flex shrink-0 items-center gap-2" onClick={(e) => { e.preventDefault(); jumpTop() }}>
            <Mark className="size-6" />
            <Wordmark className="text-[20px]" />
          </a>
          <nav className="hidden flex-1 items-center gap-7 text-[13px] text-zinc-400 md:flex">
            {NAV.map(([id, text]) => (
              <a key={id} href={`#/welcome#${id}`} onClick={(e) => { e.preventDefault(); jump(id) }}
                 className="transition-colors hover:text-zinc-100">{text}</a>
            ))}
          </nav>
          <div className="flex-1 md:hidden" />
          <Btn onClick={openApp} small>Open VibeCut</Btn>
        </div>
      </header>

      <main className="relative">
        <Hero onStart={openApp} />
        <Marquee />
        <Moves />
        <How onStart={openApp} />
        <Promise />
        <Fixes />
        <Pricing onStart={openApp} />
        <Faq />
        <Closing onStart={openApp} />
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1120px] flex-wrap items-center gap-x-6 gap-y-3 px-6 py-8 text-[13px] text-zinc-500">
          <span className="flex items-center gap-2"><Mark className="size-5" /><Wordmark className="text-[17px]" /></span>
          <span>For people who'd rather film than edit.</span>
          <span className="flex-1" />
          <a href="#/welcome" onClick={(e) => { e.preventDefault(); jump('faq') }} className="hover:text-zinc-100">FAQ</a>
          <a href="#/profile" className="hover:text-zinc-100">Your profile</a>
          <span>© {new Date().getFullYear()} VibeCut</span>
        </div>
      </footer>
    </div>
  )
}

function jump(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function jumpTop() {
  document.querySelector('.lc')?.scrollTo({ top: 0, behavior: 'smooth' })
}

/* ---------- small parts ---------- */

/** The one button on this page: solid, or an outline. */
function Btn({ children, onClick, ghost, small, className }: {
  children: ReactNode; onClick: () => void; ghost?: boolean; small?: boolean; className?: string
}) {
  return (
    <button type="button" onClick={onClick}
            className={cx('group inline-flex shrink-0 items-center justify-center gap-2 rounded-[12px] font-semibold transition-all duration-300 backdrop-blur-sm',
              small ? 'h-9 px-3.5 text-[13px]' : 'h-12 px-6 text-[15px]',
              ghost ? 'border border-white/30 text-zinc-100 hover:border-white/60 hover:bg-white/[0.12] hover:backdrop-blur-md' : 'bg-gradient-to-r text-ink shadow-lg shadow-[#FFD93D]/40 hover:shadow-xl hover:shadow-[#FFD93D]/50 hover:scale-105',
              !ghost && 'from-[#FFD93D] via-[#FFC107] to-[#FFB700]',
              className)}>
      {children}
      {!ghost && <span aria-hidden className="transition-transform duration-300 group-hover:translate-x-1">→</span>}
    </button>
  )
}

/** VibeCut's mark: one frame cut in two on a diagonal, the second shot a
    shade lighter. Plain on purpose (the user, 2026-10-23: the clapperboard
    mascot was "too cartoonish"); the same drawing is public/favicon.svg. */
function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cx('shrink-0', className)} aria-hidden>
      <defs><clipPath id="vc-mark-frame"><rect x="6.5" y="9" width="19" height="14" rx="2.5" /></clipPath></defs>
      <rect width="32" height="32" rx="9" fill="#1f5f8b" />
      <g clipPath="url(#vc-mark-frame)">
        <path d="M0 0 H18.5 L10.5 32 H0 Z" fill="#fff" />
        <path d="M20.7 0 H32 V32 H12.7 Z" fill="#fff" fillOpacity="0.6" />
      </g>
    </svg>
  )
}

/** A section's number and name, like a contents line. */
function Label({ n, children }: { n: string; children: ReactNode }) {
  return (
    <div className={cx(label, 'flex items-center gap-3')}>
      <span className="text-accent">{n}</span><span className="h-px w-8 bg-line" />{children}
    </div>
  )
}

function H2({ children, className }: { children: ReactNode; className?: string }) {
  return <h2 className={cx(display, 'mt-5 text-[40px] leading-[1.04] sm:text-[60px]', className)}>{children}</h2>
}

/** The one italic turn in each headline. */
function Em({ children, accent }: { children: ReactNode; accent?: boolean }) {
  return <em className={cx('font-serif italic', accent ? 'text-accent' : 'text-zinc-400')}>{children}</em>
}

/** Crop marks at a figure's corners. */
function Ticks() {
  return (
    <>
      {['-top-2.5 -left-2.5 border-t border-l', '-top-2.5 -right-2.5 border-t border-r', '-bottom-2.5 -left-2.5 border-b border-l', '-bottom-2.5 -right-2.5 border-b border-r'].map((c) => (
        <span key={c} aria-hidden className={cx('absolute size-3 border-zinc-500', c)} />
      ))}
    </>
  )
}

/* ---------- hero ---------- */

function Hero({ onStart }: { onStart: () => void }) {
  return (
    <section className="relative mx-auto max-w-[1120px] px-6 pt-20 pb-16 sm:pt-28 overflow-hidden">
      {/* Premium gradient background layers */}
      <div aria-hidden className="absolute -top-40 -right-40 w-96 h-96 rounded-full blur-3xl animate-pulse" style={{ background: `radial-gradient(circle, ${COLORS.accent1}25, transparent)`, animationDuration: '6s' }} />
      <div aria-hidden className="absolute top-20 -left-32 w-80 h-80 rounded-full blur-3xl animate-pulse" style={{ background: `radial-gradient(circle, ${COLORS.accent3}20, transparent)`, animationDuration: '8s' }} />
      <div aria-hidden className="absolute bottom-20 right-1/3 w-72 h-72 rounded-full blur-3xl" style={{ background: `radial-gradient(circle, ${COLORS.accent2}15, transparent)`, animationDuration: '10s' }} />

      <button type="button" onClick={() => jump('how')}
              className="lc-rise group inline-flex items-center gap-2.5 text-[13px] text-zinc-300 transition-colors hover:text-zinc-100">
        <span className="rounded-[6px] border border-accent/60 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-accent">New</span>
        Cut your day like a reel you love
        <span aria-hidden className="transition-transform group-hover:translate-x-0.5">→</span>
      </button>

      <h1 className={cx(display, 'lc-rise mt-12 text-[48px] leading-[1.1] sm:text-[120px] sm:leading-[1.05] font-bold tracking-tight')} style={{ animationDelay: '60ms' }}>
        A hundred <span className="whitespace-nowrap">clips in.</span><br />
        <span className="relative inline-block">
          <span className="text-zinc-400">One video</span>{' '}
          <span className="whitespace-nowrap ml-2" style={{
            background: `linear-gradient(135deg, ${COLORS.accent1} 0%, ${COLORS.accent2} 50%, ${COLORS.accent3} 100%)`,
            backgroundClip: 'text',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            filter: 'drop-shadow(0 0 20px rgba(255, 217, 61, 0.2))'
          }}>you'd post.</span>
        </span>
      </h1>

      <div className="lc-rise mt-12 flex flex-wrap items-end justify-between gap-8" style={{ animationDelay: '120ms' }}>
        <p className="max-w-[420px] text-[18px] leading-relaxed text-zinc-300">
          Drop your clips. Get a video with <span className="font-semibold text-white">no amateur tells</span>.
        </p>
        <div className="flex flex-wrap gap-3">
          <Btn onClick={onStart}>Start with your clips</Btn>
          <Btn ghost onClick={() => jump('moves')}>See what it can do</Btn>
        </div>
      </div>

      <div className={cx(label, 'lc-rise mt-12 flex flex-wrap gap-x-8 gap-y-2 border-t border-zinc-700/50 pt-6')} style={{ animationDelay: '180ms' }}>
        <span>Runs on your Mac</span><span>No upload</span><span>Nothing generated</span><span>Free in early access</span>
      </div>

      <figure className="lc-rise mt-20" style={{ animationDelay: '240ms' }}>
        <div className="relative">
          <Ticks />
          <BeforeAfter />
        </div>
        <figcaption className="mt-6 font-serif text-[15px] text-zinc-500 italic">Fig. 1 — a day's clips, and the video made from them.</figcaption>
      </figure>
    </section>
  )
}

/** The promise as a picture: the shoot as it arrives, then the video. Both
    drawn rather than photographed, because real screenshots show real faces.
    It flips by itself until the visitor picks a side (never with reduced motion). */
function BeforeAfter() {
  const [side, setSide] = useState<'before' | 'after'>('before')
  const [held, setHeld] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)
  useEffect(() => {
    if (held) return
    const t = window.setInterval(() => setSide((s) => (s === 'before' ? 'after' : 'before')), 3800)
    return () => window.clearInterval(t)
  }, [held])
  const pick = (s: typeof side) => { setHeld(true); setSide(s) }
  return (
    <div className="overflow-hidden rounded-[10px] border border-line bg-panel shadow-[0_50px_140px_-50px_rgba(185,217,235,0.22)]">
      <div className="flex h-10 items-center gap-1.5 border-b border-line px-3">
        <span className="size-2.5 rounded-full bg-white/15" /><span className="size-2.5 rounded-full bg-white/15" /><span className="size-2.5 rounded-full bg-white/15" />
        <span className="flex-1" />
        <div role="tablist" aria-label="Before and after" className="inline-flex rounded-[6px] border border-line p-0.5 text-[12px]">
          {([['before', 'Your clips'], ['after', 'Your video']] as const).map(([s, text]) => (
            <button key={s} type="button" role="tab" aria-selected={side === s} onClick={() => pick(s)}
                    className={cx('rounded-[4px] px-3 py-1 whitespace-nowrap transition-colors', side === s ? 'bg-white/10 text-zinc-100' : 'text-zinc-500 hover:text-zinc-200')}>{text}</button>
          ))}
        </div>
        <span className="flex-1" />
        <span className="hidden w-[42px] sm:block" />
      </div>
      <div className="grid text-left">
        <div aria-hidden={side !== 'before'} className={cx('[grid-area:1/1] transition-opacity duration-500', side === 'before' ? 'opacity-100' : 'pointer-events-none opacity-0')}><Pile /></div>
        <div aria-hidden={side !== 'after'} className={cx('[grid-area:1/1] transition-opacity duration-500', side === 'after' ? 'opacity-100' : 'pointer-events-none opacity-0')}><Mock /></div>
      </div>
    </div>
  )
}

// Muted film tones for drawn footage: nothing on this page is brighter than a clip would be.
const TINTS = ['#5f7389', '#8d7464', '#6b8170', '#9a8b5f', '#766b88', '#5f8181', '#8b6872', '#7a805f', '#63708f', '#8f7d6a']

/** A day's footage as it comes off the phone, with the tells VibeCut catches. */
function Pile() {
  const tells: Record<number, string> = { 2: 'too dark', 9: 'shaky', 13: 'same shot', 14: 'same shot', 19: 'wind', 22: 'too bright', 27: '0.6 s', 30: 'shaky' }
  return (
    <div className="flex h-full flex-col bg-black">
      <div className="flex items-center gap-2 px-4 pt-3 text-[12px] text-zinc-400">
        <span className="text-zinc-200">Sep 22 · 104 clips</span><span className="flex-1" /><span className="hidden sm:inline">4:12 of footage</span>
      </div>
      <div className="grid flex-1 grid-cols-8 content-center gap-1.5 p-4">
        {Array.from({ length: 32 }).map((_, i) => {
          const tell = tells[i]
          const dark = tell === 'too dark', bright = tell === 'too bright'
          return (
            <div key={i} className={cx('relative aspect-[4/3] overflow-hidden rounded-[3px]', tell && 'outline outline-1 outline-offset-1 outline-[#ff7a7a]')}
                 style={{ background: TINTS[(i * 7) % TINTS.length], filter: dark ? 'brightness(0.3)' : bright ? 'brightness(1.7) saturate(0.4)' : tell === 'shaky' ? 'blur(1.2px)' : undefined }}>
              {tell && <span className="absolute bottom-0 left-0 bg-[#ff7a7a] px-1 text-[8px] leading-[13px] font-semibold tracking-wide text-black uppercase">{tell}</span>}
            </div>
          )
        })}
      </div>
      <div className="flex items-center gap-2 px-4 pb-3 text-[12px] text-zinc-500">
        <span className="text-[#ff9a9a]">8 tells</span><span>·</span><span>+69 more clips</span><span className="flex-1" /><span>nothing cut yet</span>
      </div>
    </div>
  )
}

/** The editor: a shot sequence sitting on the beat, a caption lane, a music strip. */
function Mock() {
  const shots = [9, 5, 4, 7, 4, 6, 3, 7, 5, 8]
  return (
    <div className="bg-black">
      <div className="flex items-center gap-3 px-4 pt-3 text-[12px] text-zinc-400">
        <span className="truncate text-zinc-200">Sep 22 · Short 9:16</span><span className="flex-1" />
        <span className="hidden whitespace-nowrap text-zinc-500 sm:inline">Draft saved</span>
        <span className="rounded-[4px] bg-zinc-100 px-2 py-0.5 text-[11px] font-semibold text-ink">Export</span>
      </div>
      <div className="p-4">
        <div className="relative mx-auto aspect-[9/16] w-[16%] min-w-[110px] overflow-hidden rounded-[6px]">
          <Scene v={0} />
          <div className="absolute inset-x-0 bottom-0 flex flex-col">
            <Cap className="m-3 self-start text-[11px]">7:42 am · coffee run</Cap>
            <div className="mb-3 flex items-center gap-2 px-3 text-[10px] text-zinc-300">
              <span>▶</span><span>0:04 / 0:25</span>
              <span className="h-0.5 flex-1 bg-white/25"><span className="block h-0.5 w-[18%] bg-white" /></span>
            </div>
          </div>
        </div>
      </div>
      <div className="space-y-1.5 px-4 pb-4">
        <div className="flex h-4 items-end gap-[3px]">
          {Array.from({ length: 32 }).map((_, i) => <span key={i} className={cx('flex-1', i % 4 === 0 ? 'h-3 bg-accent' : 'h-1 bg-white/15')} />)}
        </div>
        <div className="flex gap-[2px]">
          {shots.map((w, i) => (
            <div key={i} className="relative h-11 rounded-[2px]" style={{ flex: w, background: TINTS[i] }}>
              {i === 0 && <span className="absolute top-1 left-1.5 text-[9px] font-semibold tracking-wider text-white uppercase">Hook</span>}
              <span className="absolute right-1.5 bottom-1 hidden text-[9px] text-white/75 sm:inline">{(w * 0.4).toFixed(1)}s</span>
            </div>
          ))}
        </div>
        <div className="flex gap-[2px]">
          <span className="h-4 truncate rounded-[2px] bg-white/10 px-1.5 text-[10px] leading-4 text-zinc-300" style={{ flex: 12 }}>A day in the city</span>
          <span style={{ flex: 14 }} />
          <span className="h-4 truncate rounded-[2px] bg-white/10 px-1.5 text-[10px] leading-4 text-zinc-300" style={{ flex: 18 }}>11:49 am · look up</span>
          <span style={{ flex: 14 }} />
        </div>
        <div className="h-4 truncate rounded-[2px] bg-accent/15 px-1.5 text-[10px] leading-4 text-accent">♪ Kara Square — Super Power Pop Rock · on the beat</div>
      </div>
    </div>
  )
}

/* ---------- the tells, scrolling ---------- */

function Marquee() {
  const tells = ['exposure jumps', 'cuts off the beat', 'a caption over a face', 'the same shot twice', 'wind in the mic', 'a 0.6 s flash of nothing', 'music drowning your voice', 'five fonts in one video', 'shaky openers', 'dark words on a dark coat', 'a chat that runs 14 s']
  const row = tells.map((t, i) => (
    <span key={i} className="flex shrink-0 items-center gap-8 pr-8 font-serif text-[24px] text-zinc-400 italic">
      <span className="line-through decoration-zinc-600/60 decoration-1">{t}</span>
      <span className="size-1.5 rounded-full" style={{ background: COLORS.accent3 }} />
    </span>
  ))
  return (
    <section className="border-y border-zinc-800/60 py-10 bg-gradient-to-r from-zinc-900/20 to-transparent" aria-label="Amateur tells VibeCut catches">
      <div className={cx(label, 'mx-auto mb-6 max-w-[1120px] px-6')}>
        <span className="text-accent">✓</span> Caught before you ever see them
      </div>
      <div className="lc-fade overflow-hidden">
        <div className="lc-marquee flex w-max">{row}{row}</div>
      </div>
    </section>
  )
}

/* ---------- what it can do: a carousel of moves ---------- */

type MoveKind = 'Captions' | 'Transitions' | 'Effects' | 'On the beat'
type Move = { kind: MoveKind; name: string; fx: string }

// Every card is a move the editor really has, under its menu name
// (overlays.ENTERS, transitions.KINDS, effects.KINDS, make.punches).
const MOVES: Move[] = [
  { kind: 'On the beat', name: 'Cut on the beat', fx: 'cuts' },
  { kind: 'Captions', name: 'Pop', fx: 'pop' },
  { kind: 'Transitions', name: 'Swipe', fx: 'whip' },
  { kind: 'Effects', name: 'Glitch', fx: 'glitch' },
  { kind: 'Captions', name: 'Typewriter', fx: 'type' },
  { kind: 'Transitions', name: 'Zoom through', fx: 'zoom' },
  { kind: 'Effects', name: 'VHS', fx: 'vhs' },
  { kind: 'On the beat', name: 'Punch in', fx: 'punch' },
  { kind: 'Captions', name: 'Stamp', fx: 'stamp' },
  { kind: 'Transitions', name: 'Light leak', fx: 'leak' },
  { kind: 'Effects', name: 'Shake', fx: 'shake' },
  { kind: 'Captions', name: 'Word by word', fx: 'word' },
  { kind: 'Transitions', name: 'Flash', fx: 'flash' },
  { kind: 'Effects', name: 'Disco', fx: 'disco' },
  { kind: 'Captions', name: 'Slide in', fx: 'slide' },
  { kind: 'Transitions', name: 'Slide up', fx: 'up' },
  { kind: 'Effects', name: 'Old film', fx: 'old' },
  { kind: 'Captions', name: 'Fade up', fx: 'fade' },
  { kind: 'Transitions', name: 'Fade', fx: 'dissolve' },
  { kind: 'Effects', name: 'Zoom in', fx: 'zoomin' },
  { kind: 'Transitions', name: 'Dip to black', fx: 'dip' },
  { kind: 'Effects', name: 'Glow', fx: 'glow' },
  { kind: 'Transitions', name: 'Blur', fx: 'blur' },
  { kind: 'Effects', name: 'Pulse', fx: 'pulse' },
  { kind: 'Effects', name: 'Film grain', fx: 'grain' },
  { kind: 'Effects', name: 'Strobe', fx: 'strobe' },
  { kind: 'Effects', name: 'Blur in', fx: 'blurin' },
  { kind: 'Effects', name: 'Vignette', fx: 'vignette' },
  { kind: 'Effects', name: 'Zoom out', fx: 'zoomout' },
]
const KINDS = ['All', 'Captions', 'Transitions', 'Effects', 'On the beat'] as const

function Moves() {
  const [kind, setKind] = useState<(typeof KINDS)[number]>('All')
  const [auto, setAuto] = useState(() => !(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false))
  const [hover, setHover] = useState(false)
  const track = useRef<HTMLDivElement>(null)
  const list = kind === 'All' ? MOVES : MOVES.filter((m) => m.kind === kind)

  const step = (dir: 1 | -1) => {
    const el = track.current
    if (!el) return
    const card = el.querySelector('figure')
    const w = (card?.getBoundingClientRect().width ?? 180) + 16
    if (dir === 1 && el.scrollLeft + el.clientWidth >= el.scrollWidth - 4) el.scrollTo({ left: 0, behavior: 'smooth' })
    else if (dir === -1 && el.scrollLeft <= 4) el.scrollTo({ left: el.scrollWidth, behavior: 'smooth' })
    else el.scrollBy({ left: dir * w, behavior: 'smooth' })
  }
  // It moves along by itself until someone touches it, and waits while hovered.
  useEffect(() => {
    if (!auto || hover) return
    const t = window.setInterval(() => step(1), 2600)
    return () => window.clearInterval(t)
  }, [auto, hover, kind])
  useEffect(() => { track.current?.scrollTo({ left: 0 }) }, [kind])
  const pad = { paddingInline: 'max(24px, calc((100% - 1072px) / 2))', scrollPaddingInline: 'max(24px, calc((100% - 1072px) / 2))' }

  return (
    <section id="moves" aria-roledescription="carousel" aria-label="What VibeCut can do" className="scroll-mt-20 py-24 relative overflow-hidden">
      {/* Background gradient accent */}
      <div aria-hidden className="absolute -right-40 top-0 w-96 h-96 rounded-full blur-3xl" style={{ background: `radial-gradient(circle, ${COLORS.accent2}15, transparent)` }} />

      <div className="relative mx-auto flex max-w-[1120px] flex-wrap items-end gap-6 px-6">
        <div className="flex-1">
          <Label n="01">What it can do</Label>
          <H2><span style={{ background: `linear-gradient(135deg, #fff, ${COLORS.accent1})`, backgroundClip: 'text', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Every move,</span> <Em>built in.</Em></H2>
        </div>
        <div className="flex gap-2">
          {([[-1, '←', 'Previous'], [1, '→', 'Next']] as const).map(([d, a, text]) => (
            <button key={d} type="button" aria-label={text} onClick={() => { setAuto(false); step(d) }}
                    className="grid size-10 place-items-center rounded-[6px] border border-line text-[15px] text-zinc-300 transition-colors hover:border-white/30 hover:text-zinc-100">{a}</button>
          ))}
        </div>
      </div>
      <div role="tablist" aria-label="Kind of move" className="mx-auto mt-8 flex max-w-[1120px] flex-wrap gap-x-6 gap-y-2 px-6">
        {KINDS.map((k) => (
          <button key={k} type="button" role="tab" aria-selected={kind === k} onClick={() => setKind(k)}
                  className={cx('border-b pb-1.5 text-[13px] transition-colors',
                    kind === k ? 'border-zinc-100 text-zinc-100' : 'border-transparent text-zinc-500 hover:text-zinc-300')}>
            {k}{k !== 'All' && <span className="ml-1.5 text-zinc-600">{MOVES.filter((m) => m.kind === k).length}</span>}
          </button>
        ))}
      </div>
      <div ref={track} style={pad}
           className="lc-track mt-10 flex snap-x snap-mandatory gap-4 overflow-x-auto pb-4"
           onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
           onPointerDown={() => setAuto(false)} onWheel={(e) => { if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) setAuto(false) }}>
        {list.map((m, i) => (
          <figure key={m.kind + m.name} className="w-[168px] shrink-0 snap-start sm:w-[184px]">
            {/* each card starts its loop at a different point, so a row never plays in lockstep */}
            <div className="lc-card relative aspect-[9/16] overflow-hidden rounded-[14px] border border-white/10 bg-gradient-to-br from-zinc-900/80 via-black to-zinc-950 shadow-xl backdrop-blur-xl transition-all hover:border-white/30 hover:shadow-2xl hover:shadow-[0_0_40px_rgba(255,217,61,0.15)] hover:from-zinc-800/90"
                 style={{ '--lc-d': `-${((i * 0.9) % 2.4).toFixed(2)}s` } as React.CSSProperties}>
              <MoveArt m={m} i={i} />
            </div>
            <figcaption className="mt-4 flex items-baseline justify-between gap-2 px-0.5">
              <span className="text-[14px] font-semibold text-zinc-100">{m.name}</span>
              <span className="text-[10px] tracking-[0.14em] whitespace-nowrap text-accent/70 uppercase">{m.kind}</span>
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  )
}

// Three made-up places as light, not drawings: dusk over water, an overcast
// coast, a street at night. No card shows anyone's face.
const SCENES = [
  'radial-gradient(60% 26% at 50% 63%, rgba(255,186,128,.9), transparent 70%), linear-gradient(180deg,#191428 0%,#5e3048 40%,#d27e58 62%,#1c1317 63%,#0b080b 100%)',
  'radial-gradient(55% 28% at 30% 28%, rgba(255,255,255,.55), transparent 70%), linear-gradient(180deg,#8297a3 0%,#c3cdcb 50%,#47616b 51%,#1b282d 100%)',
  'radial-gradient(7% 3.6% at 22% 70%, rgba(255,170,80,.95), transparent), radial-gradient(5% 2.8% at 64% 61%, rgba(255,120,90,.85), transparent), radial-gradient(8% 4% at 82% 78%, rgba(150,190,255,.75), transparent), radial-gradient(9% 4.6% at 42% 86%, rgba(255,214,150,.75), transparent), radial-gradient(70% 40% at 50% 100%, rgba(255,150,90,.18), transparent), linear-gradient(180deg,#04050b 0%,#111731 58%,#1c1525 100%)',
]

function Scene({ v = 0, className, style }: { v?: number; className?: string; style?: React.CSSProperties }) {
  return <div className={cx('absolute inset-0', className)} style={{ background: SCENES[v % SCENES.length], ...style }} />
}

/** A caption as the app draws one: white block, the rounded caption face. */
function Cap({ children, className, style }: { children: ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <span className={cx("inline-block rounded-[4px] bg-white px-2 py-0.5 font-['Nunito'] text-[13px] font-extrabold whitespace-nowrap text-[#111]", className)} style={style}>
      {children}
    </span>
  )
}

function MoveArt({ m, i }: { m: Move; i: number }) {
  const { kind, fx } = m
  if (kind === 'Captions') {
    return (
      <>
        <Scene v={0} />
        <div className="absolute inset-x-2 top-[60%] flex justify-center gap-1">
          {fx === 'word'
            ? ['coffee', 'run', '☕'].map((w, i) => <Cap key={w} className="lc-c-word" style={{ animationDelay: `calc(var(--lc-d) + ${i * 0.22}s)` }}>{w}</Cap>)
            : <Cap className={`lc-c-${fx}`}>7:42 am · coffee ☕</Cap>}
        </div>
      </>
    )
  }
  if (kind === 'Transitions') {
    const veil = fx === 'dip' ? '#000' : fx === 'flash' ? '#fff' : fx === 'leak'
      ? 'radial-gradient(60% 50% at 50% 50%, rgba(255,190,90,0.95), rgba(255,90,120,0.6) 55%, transparent 80%)' : null
    return (
      <>
        <Scene v={i} className={`lc-tr lc-ta-${fx}`} />
        <Scene v={i + 1} className={`lc-tr lc-tb-${fx}`} />
        {veil && <div className="lc-tr lc-veil absolute inset-0" style={{ background: veil, mixBlendMode: fx === 'leak' ? 'screen' : undefined }} />}
      </>
    )
  }
  if (kind === 'On the beat') {
    return (
      <>
        {fx === 'cuts'
          ? [0, 1, 2].map((v) => <Scene key={v} v={v} className="lc-b-cycle" style={{ animationDelay: `calc(var(--lc-d) + ${[0, -1.6, -0.8][v]}s)` }} />)
          : <div className="lc-b-punch absolute inset-0"><Scene v={2} /></div>}
        <div className="absolute inset-x-0 bottom-3 flex justify-center gap-1.5">
          {(fx === 'cuts' ? [0, 1, 2] : [0]).map((v) => (
            <span key={v} className={cx('size-2.5 rounded-full bg-white', fx === 'cuts' ? 'lc-b-dot' : 'lc-b-tick')}
                  style={{ animationDelay: fx === 'cuts' ? `calc(var(--lc-d) + ${[0, -1.6, -0.8][v]}s)` : undefined }} />
          ))}
        </div>
      </>
    )
  }
  // Effects: the picture moves inside a slightly larger frame so a shake never shows an edge.
  const v = ['vhs', 'glitch', 'disco', 'glow', 'strobe', 'pulse'].includes(fx) ? 2 : fx === 'old' || fx === 'grain' ? 1 : 0
  return (
    <>
      <div className={cx('absolute -inset-[6%]', `lc-e-${fx}`)}><Scene v={v} /></div>
      {fx === 'glow' && <div className="lc-o-glow absolute -inset-[6%]"><Scene v={v} /></div>}
      {fx === 'glitch' && <div className="lc-o-glitch absolute -inset-[6%]"><Scene v={v} /></div>}
      {(fx === 'grain' || fx === 'old') && <div className="lc-o-grain absolute -inset-[20%]" />}
      {fx === 'old' && <span className="lc-o-scratch absolute inset-y-0 w-px bg-white/70" />}
      {fx === 'vhs' && <div className="lc-o-vhs absolute inset-0" />}
      {fx === 'vignette' && <div className="lc-o-vignette absolute inset-0" />}
    </>
  )
}

/* ---------- how it works ---------- */

function How({ onStart }: { onStart: () => void }) {
  const steps: { n: string; title: string; text: string; art: ReactNode }[] = [
    { n: '01', title: 'Drop your clips', text: 'A folder, or a hundred files.', art: <ArtDrop /> },
    { n: '02', title: 'Make two picks', text: 'Frame and look. That’s it.', art: <ArtPicks /> },
    { n: '03', title: 'Watch, then post', text: 'Tweak in one tap. Save to Photos.', art: <ArtWatch /> },
  ]
  return (
    <section id="how" className="mx-auto max-w-[1120px] scroll-mt-20 px-6 py-24 relative">
      {/* Background accent */}
      <div aria-hidden className="absolute -left-40 top-40 w-96 h-96 rounded-full blur-3xl" style={{ background: `radial-gradient(circle, ${COLORS.accent1}12, transparent)` }} />

      <div className="relative">
        <Label n="02">How it works</Label>
        <H2>Three steps. <Em>That’s it.</Em></H2>
      <div className="mt-16 grid divide-y divide-zinc-800/60 border-y border-zinc-800/60 md:grid-cols-3 md:divide-x md:divide-y-0">
        {steps.map((s, idx) => (
          <div key={s.n} className="py-10 md:px-8 md:first:pl-0 md:last:pr-0">
            <div className="grid h-[168px] place-items-center overflow-hidden rounded-[14px] border border-white/15 bg-gradient-to-br from-zinc-900/60 via-black to-zinc-950 shadow-lg backdrop-blur-md hover:border-white/30 hover:shadow-xl transition-all">{s.art}</div>
            <div className="mt-7 flex items-baseline gap-3">
              <span className="font-serif text-[16px] font-bold" style={{ color: [COLORS.accent1, COLORS.accent2, COLORS.accent3][idx] }}>{s.n}</span>
              <h3 className={cx(display, 'text-[26px] font-semibold')}>{s.title}</h3>
            </div>
            <p className="mt-2 text-[15px] text-zinc-400">{s.text}</p>
          </div>
        ))}
      </div>
        <div className="mt-10 flex flex-wrap items-center gap-x-8 gap-y-4 rounded-[12px] border border-zinc-700/60 bg-gradient-to-r from-zinc-900/60 to-black p-8 shadow-lg">
          <span aria-hidden className="grid size-12 shrink-0 place-items-center rounded-[8px] border border-accent/30 text-[18px] font-bold" style={{ color: COLORS.accent1 }}>↗</span>
          <div className="min-w-0 flex-1 basis-[300px]">
            <h3 className={cx(display, 'text-[24px] font-semibold')}>Or paste a reel you love.</h3>
            <p className="mt-1 text-[15px] text-zinc-400">Your day, cut to its rhythm. Never its frames.</p>
          </div>
          <Btn ghost onClick={onStart}>Try it with a reel</Btn>
        </div>
      </div>
    </section>
  )
}

function ArtDrop() {
  return (
    <div className="relative h-[124px] w-[200px]">
      <div className="absolute inset-x-6 bottom-0 h-[64px] rounded-[6px] border border-dashed border-white/20" />
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="absolute top-2" style={{ left: 44 + i * 29 }}>
          <div className="lc-drop h-11 w-8 rounded-[3px]" style={{ background: TINTS[i * 2], animationDelay: `${i * 0.25}s` }} />
        </div>
      ))}
    </div>
  )
}

function ArtPicks() {
  const seg = (items: ReactNode[], on: number) => (
    <div className="inline-flex rounded-[6px] border border-line p-0.5 text-[12px]">
      {items.map((x, i) => <span key={i} className={cx('flex items-center gap-1.5 rounded-[4px] px-3 py-1', i === on ? 'bg-white/10 text-zinc-100' : 'text-zinc-500')}>{x}</span>)}
    </div>
  )
  const look = (name: string, c: string) => <><span className="size-2 rounded-[1px]" style={{ background: c }} />{name}</>
  return (
    <div className="flex flex-col items-center gap-3">
      {seg(['Short', 'Tall', 'Wide'], 0)}
      {seg([look('Cozy', '#c99a74'), look('Film', '#9c8a72'), look('Hype', '#d0667f')], 0)}
    </div>
  )
}

function ArtWatch() {
  return (
    <div className="flex items-center gap-4">
      <div className="relative grid h-[120px] w-[68px] place-items-center overflow-hidden rounded-[6px] border border-line">
        <Scene v={2} />
        <span className="relative text-[13px] text-white">▶</span>
      </div>
      <div className="flex flex-col gap-1.5">
        {['Music', '0:25', 'Cozy', 'Words'].map((x) => (
          <span key={x} className="rounded-[4px] border border-line px-2.5 py-1 text-[11px] text-zinc-300">{x}</span>
        ))}
      </div>
    </div>
  )
}

/* ---------- the promise ---------- */

function Promise() {
  const rows = [
    { share: 40, what: 'Hard constraints', c: '#ece9e4' },
    { share: 30, what: 'Editing grammar', c: 'rgba(236,233,228,.55)' },
    { share: 20, what: 'Consistency', c: 'rgba(236,233,228,.28)' },
    { share: 10, what: 'Taste', c: '#b9d9eb' },
  ]
  return (
    <section className="border-y border-line bg-panel">
      <div className="mx-auto grid max-w-[1120px] gap-14 px-6 py-24 lg:grid-cols-[1fr_1.1fr] lg:items-end">
        <div>
          <Label n="03">The promise</Label>
          <H2>Not “beautiful”.<br /><Em>No amateur tells.</Em></H2>
          <p className="mt-5 text-[16px] text-zinc-400">We fix the craft. The taste stays yours.</p>
        </div>
        <div>
          <div className="flex gap-1">
            {rows.map((r) => (
              <div key={r.what} className="min-w-0" style={{ flex: r.share }}>
                <div className="h-1.5" style={{ background: r.c }} />
                <div className="mt-5 hidden font-serif text-[40px] leading-none whitespace-nowrap sm:block">{r.share}<span className="text-[0.5em] text-zinc-500">%</span></div>
                <div className="mt-2 hidden text-[12px] leading-tight text-zinc-400 sm:block">{r.what}</div>
              </div>
            ))}
          </div>
          {/* a phone has no room under the 10%: the same numbers as a list */}
          <div className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 sm:hidden">
            {rows.map((r) => (
              <div key={r.what} className="flex items-baseline gap-2.5">
                <span className="size-2 shrink-0 self-center" style={{ background: r.c }} />
                <span className="font-serif text-[28px] leading-none">{r.share}<span className="text-[0.5em] text-zinc-500">%</span></span>
                <span className="text-[12px] leading-tight text-zinc-400">{r.what}</span>
              </div>
            ))}
          </div>
          <div className="mt-8 flex text-[11px] tracking-[0.16em] uppercase">
            <span className="border-t border-zinc-600 pt-3 text-zinc-500" style={{ flex: 90 }}>VibeCut</span>
            <span className="ml-1 border-t border-accent pt-3 text-accent" style={{ flex: 10 }}>You</span>
          </div>
        </div>
      </div>
    </section>
  )
}

/* ---------- what it fixes: a hairline grid ---------- */

function Tile({ title, text, className, children }: { title: string; text: string; className?: string; children?: ReactNode }) {
  return (
    <div className={cx('flex flex-col bg-ink p-6 transition-colors hover:bg-panel sm:p-7', className)}>
      {children && <div className="mb-6 flex flex-1 items-center">{children}</div>}
      <h3 className={cx(display, 'text-[22px]')}>{title}</h3>
      <p className="mt-1 text-[14px] text-zinc-400">{text}</p>
    </div>
  )
}

function Fixes() {
  return (
    <section id="fixes" className="mx-auto max-w-[1120px] scroll-mt-20 px-6 py-24">
      <Label n="04">What it fixes</Label>
      <H2>Amateur tells, <Em>handled.</Em></H2>
      <div className="mt-14 grid auto-rows-[minmax(220px,auto)] gap-px overflow-hidden rounded-[10px] border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
        <Tile className="sm:col-span-2 lg:row-span-2" title="Cuts on the beat" text="The drop lands right after the hook.">
          <div className="w-full">
            <div className="flex h-16 items-end gap-1">
              {Array.from({ length: 24 }).map((_, i) => (
                <span key={i} className="lc-beat flex-1" style={{ height: i % 4 === 0 ? 64 : 14 + ((i * 7) % 16), background: i % 4 === 0 ? '#b9d9eb' : 'rgba(255,255,255,.14)', animationDelay: `${(i % 4) * 0.12}s` }} />
              ))}
            </div>
            <div className="mt-2 flex gap-[3px]">
              {[4, 4, 8, 4, 4].map((w, i) => <div key={i} className="h-24 rounded-[3px]" style={{ flex: w, background: TINTS[i + 3] }} />)}
            </div>
            <div className="mt-2 flex justify-between text-[10px] tracking-[0.14em] text-zinc-500 uppercase"><span>1</span><span>2</span><span>3</span><span>4</span><span className="text-accent">Drop</span></div>
          </div>
        </Tile>
        <Tile title="One look, end to end" text="Seven looks, fitted to your footage.">
          <div className="flex w-full max-w-[240px] gap-1">
            {['#c99a74', '#9c8a72', '#d0667f', '#8e9eab', '#c4a75a', '#2b2724', '#b9b2a6'].map((c) => <span key={c} className="aspect-square flex-1 rounded-[3px] border border-white/10" style={{ background: c }} />)}
          </div>
        </Tile>
        <Tile title="Captions that read" text="Time and place, always readable.">
          <div className="relative h-20 w-full overflow-hidden rounded-[4px]">
            <Scene v={0} />
            <Cap className="absolute bottom-3 left-3 text-[12px]">11:49 am · look up</Cap>
          </div>
        </Tile>
        <Tile title="Your voice stays up" text="Music ducks when you talk.">
          <svg viewBox="0 0 200 50" className="w-full" aria-hidden>
            <path d="M0 22 Q10 4 20 22 T40 22 T60 22 T80 22 T100 22 T120 22 T140 22 T160 22 T180 22 T200 22" stroke="rgba(255,255,255,.7)" strokeWidth="1.5" fill="none" />
            <path d="M0 40 L60 40 L70 46 L140 46 L150 40 L200 40" stroke="#b9d9eb" strokeWidth="1.5" fill="none" />
          </svg>
        </Tile>
        <Tile title="No shot twice" text="Look-alikes collapse to the best.">
          <div className="flex items-center gap-2">
            <div className="h-14 w-10 rounded-[3px]" style={{ background: TINTS[4] }} />
            <div className="relative h-14 w-10 overflow-hidden rounded-[3px] opacity-40" style={{ background: TINTS[4] }}>
              <svg viewBox="0 0 40 56" className="absolute inset-0 size-full" aria-hidden><path d="M0 56 L40 0" stroke="#ff7a7a" strokeWidth="1.5" /></svg>
            </div>
          </div>
        </Tile>
        <Tile title="Every cut checked" text="Light, colour and sound at every join.">
          <div className="flex items-center gap-1">
            {[0, 1, 2, 3].map((i) => (
              <span key={i} className="flex items-center gap-1">
                <span className="h-10 w-8 rounded-[2px]" style={{ background: TINTS[i + 5] }} />
                {i < 3 && <span className={cx('text-[11px]', i === 2 ? 'text-[#ff9a9a]' : 'text-zinc-500')}>{i === 2 ? '!' : '✓'}</span>}
              </span>
            ))}
          </div>
        </Tile>
        <Tile title="Cut like a vlog" text="Wide, medium, close, every stop.">
          <div className="flex flex-col gap-2.5">
            <div className="relative h-[72px] w-[128px] border border-white/30">
              <span className="absolute inset-[18%_22%] border border-white/45" />
              <span className="absolute inset-[34%_38%] border border-accent" />
            </div>
            <span className="text-[10px] tracking-[0.14em] whitespace-nowrap text-zinc-500 uppercase">Wide · medium · <span className="text-accent">close</span></span>
          </div>
        </Tile>
        <Tile className="sm:col-span-2" title="Your footage stays home" text="Read on your Mac. Every frame is one you filmed.">
          <div className={cx(label, 'flex flex-wrap gap-x-6 gap-y-2')}>
            {['On-device', 'Only your frames', 'No account', 'Every change undoable'].map((x) => (
              <span key={x} className="flex items-center gap-2"><span className="size-1.5 bg-accent" />{x}</span>
            ))}
          </div>
        </Tile>
      </div>
    </section>
  )
}

/* ---------- pricing ---------- */

function Pricing({ onStart }: { onStart: () => void }) {
  const inc = ['Unlimited videos', 'Music, captions, looks, effects', 'Cut like any reel', 'Straight to Photos']
  return (
    <section id="pricing" className="mx-auto max-w-[1120px] scroll-mt-20 px-6 py-24 relative">
      {/* Background accent */}
      <div aria-hidden className="absolute -right-40 bottom-20 w-96 h-96 rounded-full blur-3xl" style={{ background: `radial-gradient(circle, ${COLORS.accent3}15, transparent)` }} />

      <div className="relative">
        <Label n="05">Pricing</Label>
        <H2>Free in <Em>early access.</Em></H2>
        <div className="mt-16 grid gap-6 overflow-visible md:grid-cols-2">
          <div className="flex flex-col rounded-[16px] border border-white/15 bg-gradient-to-br from-zinc-900/80 via-zinc-900/60 to-black p-8 sm:p-10 shadow-xl backdrop-blur-xl ring-1 ring-accent/30 hover:ring-accent/50 hover:shadow-2xl transition-all duration-500">
            <div className="flex items-center justify-between">
              <span className={label}>Early access</span>
              <span className="rounded-[6px] border border-accent/60 px-2 py-1 text-[10px] font-bold tracking-[0.16em] text-accent uppercase">Now</span>
            </div>
            <div className="mt-8 font-serif text-[72px] leading-none font-bold">$0</div>
            <p className="mt-3 text-[16px] text-zinc-300">Everything, on your Mac.</p>
            <ul className="mt-8 flex-1 space-y-3 border-t border-zinc-700/50 pt-6 text-[14px] text-zinc-300">
              {inc.map((x) => <li key={x} className="flex gap-3"><span style={{ color: COLORS.accent1 }}>+</span>{x}</li>)}
            </ul>
            <Btn className="mt-10 w-full" onClick={onStart}>Start with your clips</Btn>
          </div>
          <div className="flex flex-col rounded-[14px] border border-zinc-800/60 bg-gradient-to-br from-zinc-900/40 to-black p-8 sm:p-10 shadow-md">
            <span className={label}>Creator</span>
            <div className="mt-8 font-serif text-[48px] leading-none font-semibold text-zinc-400">Coming later</div>
            <p className="mt-3 text-[16px] text-zinc-500">For one person posting every week.</p>
            <ul className="mt-8 space-y-3 border-t border-zinc-800/50 pt-6 text-[14px] text-zinc-400">
              {['Everything in early access', 'Smarter picks, no key needed', 'Your taste on every Mac'].map((x) => (
                <li key={x} className="flex gap-3"><span className="text-zinc-700">+</span>{x}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  )
}

/* ---------- FAQ ---------- */

function Faq() {
  const qs = [
    ['Will it make my video beautiful?', 'It removes the amateur tells. The taste is yours.'],
    ['Does it generate video?', 'Never. Every frame is one you filmed.'],
    ['Where does my footage go?', 'Nowhere. It is read on your Mac. With your own Claude key, a few small frames are sent to pick moments, and you can turn that off.'],
    ['Can I still edit by hand?', 'Yes. One tap opens the full editor, and every change undoes.'],
    ['Windows?', 'Not yet. Mac only for now.'],
  ]
  const [open, setOpen] = useState<number | null>(0)
  return (
    <section id="faq" className="mx-auto grid max-w-[1120px] scroll-mt-20 gap-12 px-6 py-24 lg:grid-cols-[1fr_1.6fr]">
      <div>
        <Label n="06">Questions</Label>
        <H2><Em>Honest</Em> answers.</H2>
      </div>
      <div className="border-t border-line">
        {qs.map(([q, a], i) => (
          <div key={q} className="border-b border-line">
            <button type="button" aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}
                    className="flex w-full items-center justify-between gap-6 py-5 text-left font-serif text-[22px] transition-colors hover:text-white">
              {q}
              <span aria-hidden className={cx('text-[20px] text-zinc-500 transition-transform', open === i && 'rotate-45 text-zinc-100')}>+</span>
            </button>
            {open === i && <p className="max-w-[560px] pb-6 text-[15px] text-zinc-400">{a}</p>}
          </div>
        ))}
      </div>
    </section>
  )
}

/* ---------- closing ---------- */

function Closing({ onStart }: { onStart: () => void }) {
  return (
    <section className="relative overflow-hidden border-t border-zinc-800/60 bg-gradient-to-b from-zinc-900/40 to-black">
      <div aria-hidden className="absolute inset-0 opacity-40" style={{ background: `radial-gradient(circle at 50% -50%, ${COLORS.accent1}30, transparent 70%)` }} />
      <div className="relative mx-auto max-w-[1120px] px-6 py-32 text-center sm:py-40">
        <h2 className={cx(display, 'mx-auto max-w-[860px] text-[52px] leading-[1.1] text-balance font-bold sm:text-[96px] sm:leading-[1.05]')}>
          Your video is <span style={{ background: `linear-gradient(120deg, ${COLORS.accent1}, ${COLORS.accent2})`, backgroundClip: 'text', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>one drop away.</span>
        </h2>
        <div className="mt-12 flex justify-center"><Btn onClick={onStart}>Start with your clips</Btn></div>
        <p className={cx(label, 'mt-8 text-zinc-500')}>No account · No upload</p>
      </div>
    </section>
  )
}

/* ---------- motion ---------- */

// Kept here rather than in index.css: nothing else in the app moves like this.
const NOISE = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`
const CSS = `
.lc ::selection { background: #FFD93D; color: #0b2233; }
.lc-glow { background: radial-gradient(55% 55% at 50% 0%, rgba(255,217,61,.08), transparent 70%); }
.lc-glow-low { background: radial-gradient(50% 75% at 50% 100%, rgba(78,205,196,.1), transparent 70%); }
.lc-grain { opacity: .06; background-image: ${NOISE}; }
.lc-fade { -webkit-mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent); mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent); }
@keyframes lc-rise { from { opacity: 0; transform: translateY(12px) } to { opacity: 1; transform: none } }
.lc-rise { animation: lc-rise .8s cubic-bezier(.2,.7,.2,1) both; }
@keyframes lc-marquee { to { transform: translateX(-50%) } }
.lc-marquee { animation: lc-marquee 60s linear infinite; }
.lc-marquee:hover { animation-play-state: paused; }
@keyframes lc-beat { 0%,100% { transform: scaleY(1) } 50% { transform: scaleY(.55) } }
.lc-beat { transform-origin: bottom; animation: lc-beat .5s ease-in-out infinite; }
@keyframes lc-drop { 0%,100% { transform: translateY(0); opacity: 1 } 50% { transform: translateY(30px); opacity: .85 } }
.lc-drop { animation: lc-drop 2.4s ease-in-out infinite; }
/* the moves carousel: every loop is short so a card says what it does in a glance */
.lc-track { scrollbar-width: none; } .lc-track::-webkit-scrollbar { display: none; }
@keyframes lc-c-fade { 0%,10% { opacity:0; transform:translateY(8px) } 32%,84% { opacity:1; transform:none } 100% { opacity:0 } }
@keyframes lc-c-pop { 0%,10% { opacity:0; transform:scale(.3) } 22% { opacity:1; transform:scale(1.18) } 30%,84% { opacity:1; transform:scale(1) } 100% { opacity:0; transform:scale(1) } }
@keyframes lc-c-slide { 0%,10% { opacity:0; transform:translateX(-40px) } 32%,84% { opacity:1; transform:none } 100% { opacity:0; transform:none } }
@keyframes lc-c-stamp { 0%,10% { opacity:0; transform:scale(2.6) rotate(-10deg) } 19% { opacity:1; transform:scale(.9) rotate(-3deg) } 25%,84% { opacity:1; transform:scale(1) rotate(-3deg) } 100% { opacity:0; transform:scale(1) rotate(-3deg) } }
@keyframes lc-c-type { 0%,10% { clip-path:inset(0 100% 0 0) } 50%,84% { clip-path:inset(0 0 0 0); opacity:1 } 100% { clip-path:inset(0 0 0 0); opacity:0 } }
.lc-c-fade { animation: lc-c-fade 2.8s ease-out infinite; }
.lc-c-pop, .lc-c-word { animation: lc-c-pop 2.8s ease-out infinite; }
.lc-c-slide { animation: lc-c-slide 2.8s cubic-bezier(.2,.8,.2,1) infinite; }
.lc-c-stamp { animation: lc-c-stamp 2.8s ease-out infinite; }
.lc-c-type { animation: lc-c-type 2.8s steps(14) infinite; }

.lc-tr { animation-duration: 2.4s; animation-iteration-count: infinite; animation-direction: alternate; animation-timing-function: ease-in-out; }
@keyframes lc-t-in { 0%,35% { opacity:0 } 65%,100% { opacity:1 } }
@keyframes lc-t-cut { 0%,50% { opacity:0 } 50.01%,100% { opacity:1 } }
@keyframes lc-t-veil { 0%,35% { opacity:0 } 50% { opacity:1 } 65%,100% { opacity:0 } }
@keyframes lc-t-zoom-a { 0%,35% { transform:scale(1); opacity:1 } 55%,100% { transform:scale(2.4); opacity:0 } }
@keyframes lc-t-zoom-b { 0%,45% { transform:scale(.5); opacity:0 } 65%,100% { transform:scale(1); opacity:1 } }
@keyframes lc-t-up { 0%,35% { transform:translateY(100%) } 65%,100% { transform:none } }
@keyframes lc-t-whip-a { 0%,35% { transform:none; filter:blur(0) } 50% { filter:blur(6px) } 65%,100% { transform:translateX(-100%); filter:blur(0) } }
@keyframes lc-t-whip-b { 0%,35% { transform:translateX(100%); filter:blur(0) } 50% { filter:blur(6px) } 65%,100% { transform:none; filter:blur(0) } }
@keyframes lc-t-blur-a { 0%,35% { filter:blur(0) } 50%,100% { filter:blur(12px) } }
@keyframes lc-t-blur-b { 0%,50% { opacity:0; filter:blur(12px) } 50.01% { opacity:1; filter:blur(12px) } 65%,100% { opacity:1; filter:blur(0) } }
@keyframes lc-t-leak { 0%,30% { opacity:0; transform:translateX(-60%) } 50% { opacity:1 } 70%,100% { opacity:0; transform:translateX(60%) } }
.lc-tb-dissolve { animation-name: lc-t-in; }
.lc-tb-dip, .lc-tb-flash, .lc-tb-leak { animation-name: lc-t-cut; }
.lc-veil { animation-name: lc-t-veil; }
.lc-tb-leak ~ .lc-veil { animation-name: lc-t-leak; }
.lc-ta-zoom { animation-name: lc-t-zoom-a; } .lc-tb-zoom { animation-name: lc-t-zoom-b; }
.lc-tb-up { animation-name: lc-t-up; }
.lc-ta-whip { animation-name: lc-t-whip-a; } .lc-tb-whip { animation-name: lc-t-whip-b; }
.lc-ta-blur { animation-name: lc-t-blur-a; } .lc-tb-blur { animation-name: lc-t-blur-b; }

@keyframes lc-b-cycle { 0%,33.3% { opacity:1 } 33.4%,100% { opacity:0 } }
.lc-b-cycle { animation: lc-b-cycle 2.4s linear infinite; }
@keyframes lc-b-dot { 0%,33.3% { opacity:1; transform:scale(1.3) } 33.4%,100% { opacity:.35; transform:none } }
.lc-b-dot { animation: lc-b-dot 2.4s linear infinite; }
@keyframes lc-b-punch { 0% { transform:scale(1.16) } 35%,100% { transform:scale(1) } }
.lc-b-punch { animation: lc-b-punch .8s cubic-bezier(.2,.8,.2,1) infinite; }
@keyframes lc-b-tick { 0% { opacity:1; transform:scale(1.5) } 35%,100% { opacity:.35; transform:none } }
.lc-b-tick { animation: lc-b-tick .8s ease-out infinite; }

@keyframes lc-e-shake { 0%,100% { transform:translate(0,0) } 20% { transform:translate(-3%,2%) rotate(-1deg) } 40% { transform:translate(3%,-2%) rotate(1deg) } 60% { transform:translate(-2%,-3%) } 80% { transform:translate(2%,3%) rotate(.5deg) } }
.lc-e-shake { animation: lc-e-shake .35s linear infinite; }
@keyframes lc-e-zoomin { from { transform:scale(1) } to { transform:scale(1.4) } }
.lc-e-zoomin { animation: lc-e-zoomin 2.8s ease-in-out infinite; }
.lc-e-zoomout { animation: lc-e-zoomin 2.8s ease-in-out infinite reverse; }
@keyframes lc-e-pulse { 0%,100% { transform:scale(1) } 12% { transform:scale(1.12) } 40% { transform:scale(1.02) } }
.lc-e-pulse { animation: lc-e-pulse .7s ease-out infinite; }
@keyframes lc-e-strobe { 0%,40% { filter:none } 45%,55% { filter:brightness(2.4) saturate(.3) } 60%,100% { filter:none } }
.lc-e-strobe { animation: lc-e-strobe .45s steps(1) infinite; }
@keyframes lc-e-blurin { 0% { filter:blur(14px); transform:scale(1.15) } 45%,100% { filter:blur(0); transform:scale(1) } }
.lc-e-blurin { animation: lc-e-blurin 2.8s ease-out infinite; }
@keyframes lc-e-disco { to { filter:hue-rotate(360deg) saturate(1.6) } }
.lc-e-disco { animation: lc-e-disco 1.6s linear infinite; }
@keyframes lc-e-old { 0%,100% { filter:sepia(.85) contrast(1.1) } 50% { filter:sepia(.85) contrast(1.1) brightness(.8) } }
.lc-e-old { animation: lc-e-old .3s steps(2) infinite; }
@keyframes lc-e-vhs { 0%,46%,54%,100% { transform:none } 50% { transform:skewX(-5deg) translateX(3%) } }
.lc-e-vhs { filter: saturate(1.6) contrast(1.1); animation: lc-e-vhs 1.4s linear infinite; }
@keyframes lc-o-glow { 0%,100% { opacity:.2 } 50% { opacity:.9 } }
.lc-o-glow { filter: blur(10px) brightness(1.5); mix-blend-mode: screen; animation: lc-o-glow 1.6s ease-in-out infinite; }
@keyframes lc-o-glitch { 0%,100% { clip-path:inset(0 0 100% 0); transform:none } 10% { clip-path:inset(20% 0 60% 0); transform:translateX(-9%) } 20% { clip-path:inset(55% 0 25% 0); transform:translateX(7%) } 30% { clip-path:inset(0 0 100% 0) } 60% { clip-path:inset(70% 0 12% 0); transform:translateX(-6%) } 70% { clip-path:inset(0 0 100% 0) } }
.lc-o-glitch { filter: hue-rotate(150deg) saturate(2); animation: lc-o-glitch 1.2s steps(1) infinite; }
@keyframes lc-o-grain { 0% { transform:translate(0,0) } 25% { transform:translate(-5%,4%) } 50% { transform:translate(4%,-3%) } 75% { transform:translate(-3%,-5%) } }
.lc-o-grain { opacity:.55; mix-blend-mode: overlay; animation: lc-o-grain .4s steps(1) infinite;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E"); }
@keyframes lc-o-scratch { 0%,100% { left:30%; opacity:.7 } 33% { left:62%; opacity:.2 } 66% { left:45%; opacity:.8 } }
.lc-o-scratch { animation: lc-o-scratch .5s steps(1) infinite; }
@keyframes lc-o-vhs { from { background-position: 0 0, 0 -40% } to { background-position: 0 4px, 0 140% } }
.lc-o-vhs { background: repeating-linear-gradient(0deg, rgba(0,0,0,.22) 0 1px, transparent 1px 4px), linear-gradient(transparent 0 45%, rgba(255,255,255,.18) 50%, transparent 55%);
  background-size: 100% 4px, 100% 100%; background-repeat: repeat, no-repeat; animation: lc-o-vhs 2.2s linear infinite; }
@keyframes lc-o-vignette { 0%,100% { opacity:.6 } 50% { opacity:1 } }
.lc-o-vignette { background: radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,.8) 80%); animation: lc-o-vignette 2.4s ease-in-out infinite; }
.lc .lc-card * { animation-delay: var(--lc-d, 0s); }
@media (prefers-reduced-motion: reduce) {
  .lc *, .lc *::before { animation: none !important; transition: none !important; }
}
/* Premium aesthetic enhancements */
@keyframes subtle-glow { 0%, 100% { opacity: 0.5; } 50% { opacity: 0.8; } }
@keyframes float { 0%, 100% { transform: translateY(0px); } 50% { transform: translateY(-8px); } }
.lc-card { transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1); }
.lc-card:hover { transform: translateY(-4px) scale(1.02); filter: brightness(1.08); }
.lc-rise { animation: float 4s ease-in-out infinite; }
/* Subtle text glow on hover */
.lc h2:hover { text-shadow: 0 0 30px rgba(255, 217, 61, 0.15); }
/* Interactive link hover */
a:hover { transition: all 0.3s ease; }
/* Button premium effects */
button:active { transform: scale(0.97); }
/* Smooth transitions */
* { transition: color 0.3s ease, background-color 0.3s ease; }
`
