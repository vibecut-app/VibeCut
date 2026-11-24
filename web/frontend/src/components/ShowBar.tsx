import { Button } from '../ui'

// Watch it edit (makeShow.ts): the one line above the timeline saying what
// VibeCut is doing, how far along it is, and Skip. Under it, the whole page
// is covered by a clear layer, so nothing can be clicked or typed into while
// the moves play: the edit has already landed, and is the creator's the
// moment it's done or skipped.
export function ShowBar({ say, k, n, onSkip }: { say: string; k: number; n: number; onSkip: () => void }) {
  return (
    <>
      <div className="fixed inset-0 z-[60] cursor-progress" aria-hidden onPointerDown={(e) => e.preventDefault()} />
      <div className="relative z-[61] my-1.5 flex shrink-0 items-center gap-3 rounded-2xl border border-line bg-panel px-4 py-2 shadow-sm">
        <span className="relative flex size-2.5 shrink-0" aria-hidden>
          <span className="absolute inline-flex size-full rounded-full bg-accent opacity-60 motion-safe:animate-ping" />
          <span className="relative inline-flex size-2.5 rounded-full bg-accent" />
        </span>
        <div className="min-w-0 flex-1">
          <p role="status" aria-live="polite" className="truncate font-serif text-[17px] text-zinc-100">{say}…</p>
          <div className="mt-1 h-0.5 overflow-hidden rounded-full bg-raised" aria-hidden>
            <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${Math.round(((k + 1) / Math.max(1, n)) * 100)}%` }} />
          </div>
        </div>
        <span className="hidden shrink-0 font-serif text-[14px] text-muted sm:block">Watch VibeCut edit</span>
        <Button size="sm" onClick={onSkip} title="Go straight to the finished video (Esc)">Skip</Button>
      </div>
    </>
  )
}
