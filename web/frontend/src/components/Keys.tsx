// The keyboard, as NLE editors already know it.
const ROWS: [string, string][] = [
  ['Space', 'Play / pause'],
  ['J · K · L', 'Play backwards · stop · play forwards — press J or L again to go faster'],
  ['I · O', 'Mark where a section starts · ends   (⌥X clears the marks)'],
  ['← →', 'Move one frame'],
  ['⇧ ← →', 'Move one second'],
  ['⌥ ← →', 'Jump to the previous / next moment the playhead sticks to'],
  ['↑ ↓', 'Jump to the previous / next change of shot'],
  ['B  or  ⌘K', 'Cut the shot in two here — while playing, it lands on the nearest moment'],
  ['⌘D', 'Duplicate the clicked shot, right after itself'],
  ['⌥⌘C  /  ⌥⌘V', 'Copy the clicked shot’s settings / paste them onto another shot'],
  ['Q · W', 'Trim this shot so it starts · ends here; the rest moves up'],
  ['⌥Q · ⌥W', 'Same, but leave empty space instead'],
  [', .', 'Make this shot one frame shorter · longer'],
  ['⇧ , .', '… one second'],
  ['⌘ , .', '… one beat of the music (when a track is in use)'],
  ['Delete', 'Remove the marked section, or the selected shot — the rest moves up'],
  ['⌥ Delete', 'Same, but leave empty space instead'],
  ['⌘Z · ⇧⌘Z', 'Undo · redo'],
  ['⌘ + scroll  or  pinch', 'Zoom the timeline around the pointer — all the way in to single frames'],
  ['⌘= · ⌘−', 'Zoom the timeline in · out'],
  ['⇧Z', 'Fit the whole video in the timeline'],
  ['Hold ⌥ while dragging the playhead', 'Don’t stick — go exactly where you point'],
  ['Time box', 'Type 21.3, 0:21.3 or 00:00:21:09 and press Enter — goes exactly there'],
]

export function Keys({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/50" onClick={onClose}>
      <div className="w-[560px] rounded-xl border border-line bg-panel p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-baseline justify-between">
          <h3 className="font-serif text-[18px] text-zinc-100">Keyboard</h3>
          <span className="text-[11px] text-muted">Esc to close</span>
        </div>
        <dl className="grid grid-cols-[150px_1fr] gap-x-4 gap-y-1.5 text-[12px]">
          {ROWS.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="font-mono text-zinc-200">{k}</dt>
              <dd className="text-zinc-400">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}
