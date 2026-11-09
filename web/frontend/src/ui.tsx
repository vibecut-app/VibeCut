import { useEffect, type ButtonHTMLAttributes, type ReactNode } from 'react'

// The few controls every screen is built from, so they all look and behave
// the same. Tokens live in index.css (ink / panel / raised / line / muted /
// accent). Prose and headings are serif; dense UI labels are sans.

export const cx = (...xs: (string | false | null | undefined)[]) => xs.filter(Boolean).join(' ')

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
const VARIANT: Record<Variant, string> = {
  primary: 'bg-accent font-semibold text-accent-ink hover:brightness-110',
  secondary: 'border border-line text-zinc-200 hover:bg-raised',
  ghost: 'text-muted hover:text-zinc-100',
  danger: 'border border-rose-400/40 text-rose-200 hover:bg-rose-500/10',
}
// Buttons speak in the same serif as the headings and captions (sarah,
// 2026-10-06: one font); Garamond runs small, hence the larger sizes.
const SIZE = { sm: 'px-2.5 py-1 text-[14px]', md: 'px-3 py-1.5 text-[15px]', lg: 'px-4 py-2 text-[17px]' } as const

export function Button({ variant = 'secondary', size = 'md', className, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: keyof typeof SIZE }) {
  return <button type="button" {...props}
                 className={cx('inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg font-serif leading-none transition-colors disabled:cursor-default disabled:opacity-35 disabled:hover:bg-transparent',
                   VARIANT[variant], SIZE[size], variant === 'primary' && 'disabled:hover:bg-accent', className)} />
}

export const inputCls = 'w-full rounded-lg border border-line bg-ink px-3 py-2 text-[13px] text-zinc-100 outline-none placeholder:text-zinc-500 focus:border-accent/60 disabled:opacity-50'

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-[12px] text-zinc-300">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="mt-1 block text-[11px] text-muted">{hint}</span>}
    </label>
  )
}

/** A choice made of pills; one or many. */
export function Pills({ values, selected, onPick, disabled }: {
  values: readonly string[]; selected: string[]; onPick: (v: string) => void; disabled?: boolean
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((v) => (
        <button key={v} type="button" disabled={disabled} aria-pressed={selected.includes(v)} onClick={() => onPick(v)}
                className={cx('rounded-full border px-3 py-1 text-[12px] transition-colors',
                  selected.includes(v) ? 'border-accent bg-accent text-accent-ink' : 'border-line text-zinc-300 hover:border-zinc-500')}>
          {v}
        </button>
      ))}
    </div>
  )
}

type Tone = 'info' | 'ok' | 'warn' | 'bad'
const TONE: Record<Tone, string> = {
  info: 'border-line bg-raised text-zinc-300',
  ok: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200',
  warn: 'border-amber-300/30 bg-amber-300/10 text-amber-100',
  bad: 'border-rose-400/40 bg-rose-500/10 text-rose-200',
}
export function Notice({ tone = 'info', children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <div role={tone === 'bad' ? 'alert' : undefined} className={cx('rounded-lg border px-3 py-2 text-[12px] leading-snug', TONE[tone], className)}>{children}</div>
}

export function Progress({ frac, tone = 'accent', className }: { frac: number; tone?: 'accent' | 'bad'; className?: string }) {
  return (
    <div className={cx('h-1.5 overflow-hidden rounded-full bg-zinc-800', className)}>
      <div className={cx('h-full rounded-full transition-[width] duration-300', tone === 'bad' ? 'bg-rose-400' : 'bg-accent')}
           style={{ width: `${Math.max(0, Math.min(1, frac)) * 100}%` }} />
    </div>
  )
}

/** One modal shell: dims the app, closes on Escape or a click outside (unless busy). */
export function Dialog({ title, sub, onClose, busy, width = 480, children, footer, id = 'dialog-title' }: {
  title: ReactNode; sub?: ReactNode; onClose: () => void; busy?: boolean; width?: number
  children: ReactNode; footer?: ReactNode; id?: string
}) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [busy, onClose])
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-[2px]"
         onPointerDown={(e) => { if (e.target === e.currentTarget && !busy) onClose() }}>
      <div role="dialog" aria-labelledby={id} style={{ width, maxWidth: 'calc(100vw - 32px)' }}
           className="max-h-[92vh] overflow-y-auto rounded-2xl border border-line bg-panel p-5 shadow-2xl shadow-black/60">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 id={id} className="font-serif text-[24px] leading-tight text-zinc-100">{title}</h2>
            {sub && <p className="mt-1 text-[12px] leading-snug text-zinc-400">{sub}</p>}
          </div>
          <button type="button" aria-label="Close" disabled={busy} onClick={onClose}
                  className="grid size-7 shrink-0 place-items-center rounded-md text-muted hover:bg-raised hover:text-zinc-100 disabled:opacity-30">✕</button>
        </div>
        <div className="mt-4">{children}</div>
        {footer && <div className="mt-5 flex flex-wrap items-center justify-end gap-2">{footer}</div>}
      </div>
    </div>
  )
}

export function Wordmark({ className }: { className?: string }) {
  return <span className={cx('font-serif text-[21px] font-semibold tracking-tight text-zinc-100', className)}>Vibe<span className="text-accent">Cut</span></span>
}

/** Small uppercase section label. */
export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx('text-[11px] font-semibold uppercase tracking-wider text-muted', className)}>{children}</span>
}

export function Spinner({ className }: { className?: string }) {
  return <span className={cx('inline-block size-2 animate-pulse rounded-full bg-accent align-middle', className)} aria-hidden />
}

/** Confirm before something that is hard to take back. A little larger and
 *  heavier than other dialogs (sarah, 2026-11-09: "slightly bigger and the
 *  fonts more readable by bolding"): it is read once, carefully. */
export function Confirm({ title, text, action, danger, onYes, onNo }: {
  title: string; text: ReactNode; action: string; danger?: boolean; onYes: () => void; onNo: () => void
}) {
  return (
    <Dialog title={<span className="text-[28px] font-semibold">{title}</span>} onClose={onNo} width={460} id="confirm-title"
            footer={<>
              <Button variant="ghost" size="lg" className="font-semibold text-zinc-300" onClick={onNo}>Keep it</Button>
              <Button variant={danger ? 'danger' : 'primary'} size="lg" className="font-semibold" onClick={onYes}>{action}</Button>
            </>}>
      <p className="text-[15px] font-medium leading-relaxed text-zinc-200">{text}</p>
    </Dialog>
  )
}

export const ago = (t: number): string => {
  const s = Math.max(0, Date.now() / 1000 - t)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} d ago`
  return new Date(t * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}
