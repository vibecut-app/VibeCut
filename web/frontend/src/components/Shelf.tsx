import { useRef, useState } from 'react'
import type { Clip } from '../types'
import { dur } from '../format'
import { Button, cx } from '../ui'

export const SHOT_MIME = 'application/x-vibecut-shot'

type Tab = 'all' | 'kept' | 'out'

// Media on the edit screen: every clip as a grid, with All / Kept / Left out
// tabs (sarah, 2026-10-16: the layout of her reference picture; before that
// two piles, 2026-10-13). Kept means in the video and wears a tick; Left out
// is the dark red of Footage. Clicking a clip plays it and offers the move
// (no note on why it is out; sarah, 2026-10-20). A move changes the video as
// one undoable turn. A clip can also be dragged onto the timeline.
export function Shelf({ clips, inEdit, onPreview, onMove, onPick, busy }: {
  clips: Clip[]
  /** ids of the clips the edit uses */
  inEdit: Set<string>
  onPreview: (clip: Clip) => void
  onMove: (clip: Clip, into: boolean) => Promise<void>
  onPick: (files: FileList) => void
  busy: boolean
}) {
  const folderInput = useRef<HTMLInputElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const [tab, setTab] = useState<Tab>('all')
  const [chosen, setChosen] = useState<string | null>(null)
  const [moving, setMoving] = useState(false)
  const [menu, setMenu] = useState(false)
  const kept = clips.filter((c) => inEdit.has(c.id))
  const out = clips.filter((c) => !inEdit.has(c.id))
  const shown = tab === 'kept' ? kept : tab === 'out' ? out : clips
  const pick = clips.find((c) => c.id === chosen) ?? null

  const tabs: [Tab, string, number | null][] = [['all', 'All', null], ['kept', 'Kept', kept.length], ['out', 'Left out', out.length]]

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 px-4">
        <span className="font-serif text-[19px] text-zinc-100">All clips</span>
        <span className="rounded-md bg-raised px-1.5 text-[13px] tabular-nums text-zinc-300">{clips.length}</span>
        <div className="flex-1" />
        <Button size="sm" disabled={busy} onClick={() => fileInput.current?.click()}>+ Add more</Button>
        <div className="relative">
          <Button size="sm" aria-label="More ways to add" aria-expanded={menu} onClick={() => setMenu((m) => !m)}>···</Button>
          {menu && (
            <div className="absolute right-0 top-9 z-30 w-48 rounded-xl border border-line bg-panel p-1.5 shadow-xl">
              <button type="button" disabled={busy} onClick={() => { setMenu(false); folderInput.current?.click() }}
                      className="block w-full rounded-md px-2.5 py-1.5 text-left font-serif text-[15px] text-zinc-100 hover:bg-raised">Add a folder…</button>
            </div>
          )}
        </div>
        <input ref={fileInput} type="file" className="hidden" multiple accept=".mp4,.mov,video/mp4,video/quicktime"
               onChange={(e) => { if (e.target.files) onPick(e.target.files); e.target.value = '' }} />
        {/* @ts-expect-error -- non-standard but supported everywhere that matters */}
        <input ref={folderInput} type="file" className="hidden" webkitdirectory="" multiple
               onChange={(e) => { if (e.target.files) onPick(e.target.files); e.target.value = '' }} />
      </header>

      {clips.length === 0 ? (
        <button type="button" onClick={() => folderInput.current?.click()}
                className="m-4 grid flex-1 place-items-center rounded-xl border border-dashed border-zinc-700 text-center hover:border-zinc-500">
          <div>
            <div className="font-serif text-[18px] text-zinc-200">Drop a folder or clips here</div>
            <div className="mt-1 font-serif text-[16px] text-zinc-300">.mp4 and .mov · they stay on this Mac, nothing is uploaded</div>
          </div>
        </button>
      ) : <>
        <div role="tablist" className="mx-4 flex shrink-0 rounded-xl bg-raised p-1">
          {tabs.map(([id, name, n]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
                    className={cx('flex flex-1 items-center justify-center gap-1.5 rounded-lg py-1.5 font-serif text-[15px]',
                      tab === id ? 'bg-panel text-accent shadow-sm' : id === 'out' ? 'text-rose-200 hover:bg-panel/60' : 'text-zinc-300 hover:bg-panel/60')}>
              {name}
              {n != null && <span className="rounded bg-zinc-800 px-1 text-[12px] tabular-nums text-zinc-300">{n}</span>}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {!shown.length
            ? <p className="mt-10 text-center font-serif text-[17px] text-zinc-200">{tab === 'out' ? 'Every clip is in the video.' : 'Nothing in the video yet.'}</p>
            : (
              <div className="grid auto-rows-min grid-cols-[repeat(auto-fill,minmax(92px,1fr))] gap-2.5">
                {shown.map((c) => {
                  const on = chosen === c.id
                  const used = inEdit.has(c.id)
                  const first = c.shots[0]
                  return (
                    <button key={c.id} type="button"
                            draggable={!!first}
                            onDragStart={(e) => { if (first) { e.dataTransfer.setData(SHOT_MIME, first.id); e.dataTransfer.effectAllowed = 'copy' } }}
                            onClick={() => { setChosen(on ? null : c.id); if (!on) onPreview(c) }}
                            title={c.name}
                            className={cx('relative aspect-square select-none overflow-hidden rounded-lg bg-black outline-none',
                              on ? 'ring-[3px] ring-accent' : used ? 'ring-1 ring-zinc-800 hover:ring-2 hover:ring-zinc-600' : 'ring-2 ring-rose-200/70 hover:ring-rose-300')}>
                      {first && <img src={first.thumb} alt="" loading="lazy" draggable={false} className="size-full object-cover" />}
                      {used
                        ? <span aria-label="In the video" className="absolute left-1.5 top-1.5 grid size-5 place-items-center rounded-full bg-accent text-[12px] text-white ring-2 ring-white">✓</span>
                        : <span className="absolute inset-0 bg-rose-50/25" />}
                      <span className="absolute bottom-1.5 left-1.5 rounded bg-black/70 px-1 text-[12px] tabular-nums text-white">{dur(c.duration)}</span>
                    </button>
                  )
                })}
              </div>
            )}
        </div>

        {pick ? (
          <div className="flex shrink-0 flex-col gap-2 border-t border-line px-4 py-3">
            <div className="flex items-baseline gap-2">
              <span className="min-w-0 flex-1 truncate font-serif text-[16px] text-zinc-100">{pick.name}</span>
              <span className={cx('shrink-0 font-serif text-[15px]', inEdit.has(pick.id) ? 'text-accent' : 'text-rose-200')}>
                {inEdit.has(pick.id) ? 'In the video' : 'Left out'}</span>
            </div>
            <Button variant="primary" disabled={moving}
                    onClick={async () => {
                      setMoving(true)
                      try { await onMove(pick, !inEdit.has(pick.id)); setChosen(null) } finally { setMoving(false) }
                    }}>
              {moving ? 'Moving…' : `Move to ${inEdit.has(pick.id) ? 'Left out' : 'Kept'}`}
            </Button>
          </div>
        ) : (
          <p className="shrink-0 border-t border-line px-4 py-3 text-center font-serif text-[16px] text-zinc-200">Click a clip to play it.</p>
        )}
      </>}
    </section>
  )
}
