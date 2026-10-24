import { useEffect, useRef, useState } from 'react'
import { api, type ShareHow, type SharePlatform, type ShareTargets } from '../api'
import type { ExportJob } from '../types'
import { YouTubePost } from './YouTubePost'

// After an export: keep the file, hand it on, or take it to a platform.
// VibeCut never posts by itself -- a platform button copies the caption and opens
// that platform's own upload page, where the creator picks the file and
// presses post. Each platform is checked against the file first (backend
// share.py) and a mismatch is said, not hidden. Every way out is recorded
// on the project (kind "share") for the launch log.
// YouTube can also be posted from here, behind its own confirm screen
// (YouTubePost.tsx), when it's set up on this Mac.

// The share sheet (AirDrop, Messages, Mail) through the browser, when it
// can take a file at all; Safari can, many others can't.
export function canShareFiles(): boolean {
  try {
    return typeof navigator.canShare === 'function'
      && navigator.canShare({ files: [new File([''], 'test.mp4', { type: 'video/mp4' })] })
  } catch { return false }
}

const btn = 'rounded-lg border border-line px-3 py-1.5 text-[12px] text-zinc-200 hover:bg-raised'

export function SharePanel({ job, caption }: { job: ExportJob; caption: string }) {
  const [targets, setTargets] = useState<ShareTargets | null>(null)
  const [ytReady, setYtReady] = useState<boolean | null>(null)   // posting from here is set up on this Mac
  const [posting, setPosting] = useState(false)
  const [said, setSaid] = useState<{ text: string; finder?: boolean } | null>(null)
  const [sheet] = useState(canShareFiles)
  const file = useRef<Promise<File> | null>(null)
  const mac = targets ? targets.mac : navigator.platform.startsWith('Mac')
  const name = job.file ?? 'the video'
  // where the file is, as the creator would say it: "Movies/VibeCut"
  const folder = (job.path ?? '').split('/').slice(-3, -1).join('/') || 'your exports folder'

  useEffect(() => { api.exportShare(job.id).then(setTargets).catch(() => setTargets(null)) }, [job.id])
  useEffect(() => { api.youtube().then((s) => setYtReady(s.configured)).catch(() => setYtReady(false)) }, [])
  // The sheet must open within the click, so the file is fetched before it.
  useEffect(() => {
    if (!sheet) return
    file.current = fetch(`/api/export/${job.id}/file`).then((r) => r.blob()).then((b) => new File([b], name, { type: 'video/mp4' }))
    file.current.catch(() => {})
  }, [job.id, name, sheet])

  const record = (how: ShareHow) => { api.exportShared(job.id, how).catch(() => {}) }
  const copy = (): Promise<boolean> => (navigator.clipboard?.writeText(caption) ?? Promise.reject()).then(() => true, () => false)

  const shareSheet = async () => {
    try {
      const f = await file.current!
      await navigator.share({ files: [f], title: name, text: caption || undefined })
      record('sheet')
      setSaid({ text: 'Shared.' })
    } catch (e) {
      const n = (e as Error).name
      if (n === 'AbortError') return
      setSaid({ text: n === 'NotAllowedError' ? 'The file is ready now — press Share again.' : 'Sharing didn’t work here. Download it instead.' })
    }
  }

  // The link itself opens the platform's page in a new tab (a real link, so
  // no popup blocker stops it); the click copies first, while this page
  // still has focus.
  const go = (p: SharePlatform) => {
    const copied = caption ? copy() : Promise.resolve(false)
    record(p.id)
    copied.then((ok) => setSaid({
      text: `${ok ? 'Caption copied. ' : caption ? 'Couldn’t copy the caption — use Copy caption. ' : ''}`
        + `On ${p.where}, choose “${name}” from ${folder}${mac ? ' or drag it in from Finder' : ''}${ok ? ', paste the caption' : ''}, and post.`,
      finder: mac,
    }))
  }

  return (
    <div className="mt-3 rounded-lg border border-line px-2.5 py-2.5">
      <p className="font-serif text-[14px] text-zinc-100">Share it</p>

      <div className="mt-2 flex flex-wrap gap-1.5">
        <a href={`/api/export/${job.id}/file`} download onClick={() => record('download')} className={btn}>Download</a>
        {mac && <button type="button" className={btn}
                        onClick={async () => { setSaid({ text: 'Saving to Photos…' }); try { await api.exportPhotos(job.id); setSaid({ text: 'In Photos — your iPhone has it too if iCloud Photos is on.' }) } catch (e) { setSaid({ text: (e as Error).message }) } }}>
          Save to Photos</button>}
        {mac && <button type="button" className={btn} onClick={() => api.exportReveal(job.id)}>Show in Finder</button>}
        {sheet && <button type="button" className={btn} onClick={shareSheet} title="AirDrop, Messages, Mail…">Share…</button>}
      </div>
      {!sheet && <p className="mt-1 text-[11px] leading-snug text-muted">
        This browser can’t hand the file to AirDrop or Messages{mac ? ' — Save to Photos or Show in Finder does it from there.' : '. Download it, then share it from your files.'}</p>}

      <p className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-muted">Post it</p>
      {posting ? <YouTubePost job={job} onClose={() => setPosting(false)} /> : targets ? (<>
        <ul className="mt-1.5 space-y-1.5">
          {targets.platforms.map((p) => (
            <li key={p.id} className="flex items-start gap-2">
              <a href={p.url} target="_blank" rel="noopener noreferrer" onClick={() => go(p)} title={`Copies the caption and opens ${p.where} in a new tab`}
                 className={`flex w-[136px] shrink-0 items-center justify-between rounded-lg px-3 py-1.5 text-[12px] ${p.ok ? 'bg-accent/20 text-zinc-100 hover:bg-accent/30' : 'border border-line text-zinc-300 hover:bg-raised'}`}>
                {p.name}<span aria-hidden className="text-[11px] text-muted">↗</span></a>
              <span className={`min-w-0 self-center text-[11px] leading-snug ${p.ok ? 'text-muted' : 'text-amber-200'}`}>
                {p.why ?? p.note ?? 'Fits.'}</span>
            </li>
          ))}
        </ul>
        {ytReady ? (
          <button type="button" onClick={() => setPosting(true)} className="mt-2 text-[12px] text-accent hover:underline">
            Or post it to your YouTube channel from here…</button>
        ) : ytReady === false && (
          <p className="mt-2 text-[11px] leading-snug text-muted">Posting to YouTube straight from VibeCut isn’t set up on this Mac yet (see “Posting to YouTube” in web/README.md).</p>
        )}
      </>) : <p className="mt-1 text-[11px] text-muted">Checking where it fits…</p>}

      <div className="mt-2 flex items-center gap-2">
        <button type="button" title="The caption to paste: the title line, and the music credit its licence asks for"
                disabled={!caption}
                onClick={() => copy().then((ok) => { setSaid({ text: ok ? 'Caption copied.' : 'Copy failed.' }); if (ok) record('caption') })}
                className="text-[11px] text-accent hover:underline disabled:text-zinc-600 disabled:no-underline">
          {caption ? `Copy caption${caption.includes('\nMusic: ') || caption.startsWith('Music: ') ? ' + credit' : ''}` : 'No caption to copy'}</button>
      </div>
      {said && <p className="mt-1.5 text-[11px] leading-snug text-zinc-300">{said.text}
        {said.finder && <> <button type="button" onClick={() => api.exportReveal(job.id)} className="text-accent hover:underline">Show in Finder</button></>}</p>}
      <p className="mt-2 text-[10px] leading-snug text-zinc-500">VibeCut never posts by itself — only when you press Post.</p>
    </div>
  )
}
