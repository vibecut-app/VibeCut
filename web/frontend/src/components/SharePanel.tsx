import { useEffect, useRef, useState } from 'react'
import { api, type ShareCover, type ShareHow, type SharePlatform, type ShareTargets } from '../api'
import type { ExportJob } from '../types'
import { YouTubePost } from './YouTubePost'

// After an export: keep the file, hand it on, or take it to a platform.
// VibeCut never posts by itself -- a platform button copies the caption and opens
// that platform's own upload page, where the creator picks the file and
// presses post. Each platform is checked against the file first (backend
// share.py) and a mismatch is said, not hidden. Every way out is recorded
// on the project (kind "share") for the launch log.
// YouTube can also be posted from here, behind its own confirm screen
// (YouTubePost.tsx), when it's set up on this Mac. The words to post with
// start as a draft from what the edit knows (backend postcopy.py) and are
// the creator's to change; the music credit is added to whatever they
// write. The cover is one of the video's own frames (covers.py).

// The share sheet (AirDrop, Messages, Mail) through the browser, when it
// can take a file at all; Safari can, many others can't.
export function canShareFiles(): boolean {
  try {
    return typeof navigator.canShare === 'function'
      && navigator.canShare({ files: [new File([''], 'test.mp4', { type: 'video/mp4' })] })
  } catch { return false }
}

const btn = 'rounded-lg border border-line px-3 py-1.5 text-[12px] text-zinc-200 hover:bg-raised'

// `onOther`: export the same edit in the other frame (the dialog runs it)
export function SharePanel({ job, caption: fallback, onOther }: { job: ExportJob; caption: string; onOther?: (frame: 'tall' | 'wide') => void }) {
  const [targets, setTargets] = useState<ShareTargets | null>(null)
  const [words, setWords] = useState<string | null>(null)        // null = the draft, untouched
  const [cover, setCover] = useState<ShareCover | null>(null)
  const [picking, setPicking] = useState<number | null>(null)
  const [ytReady, setYtReady] = useState<boolean | null>(null)   // posting from here is set up on this Mac
  const [posting, setPosting] = useState(false)
  const [said, setSaid] = useState<{ text: string; finder?: boolean } | null>(null)
  const [sheet] = useState(canShareFiles)
  const file = useRef<Promise<File> | null>(null)
  const mac = targets ? targets.mac : navigator.platform.startsWith('Mac')
  const name = job.file ?? 'the video'
  // where the file is, as the creator would say it: "Movies/VibeCut"
  const folder = (job.path ?? '').split('/').slice(-3, -1).join('/') || 'your exports folder'

  useEffect(() => {
    api.exportShare(job.id).then((t) => { setTargets(t); setCover(t.cover) }).catch(() => setTargets(null))
  }, [job.id])
  const credit = targets ? targets.credit : null
  const text = words ?? targets?.post.caption ?? ''
  // what is copied: the creator's words, then the credit the song's licence asks for
  const caption = targets ? [text.trim(), credit ? `Music: ${credit}` : ''].filter(Boolean).join('\n\n') : fallback

  const pickCover = async (t: number) => {
    setPicking(t)
    try { setCover(await api.exportCover(job.id, t)) } catch (e) { setSaid({ text: (e as Error).message }) }
    finally { setPicking(null) }
  }
  const tall = job.size.h > job.size.w
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
      text: `${ok ? 'Words copied. ' : caption ? 'Couldn’t copy the words — use Copy the words. ' : ''}`
        + `On ${p.where}, choose “${name}” from ${folder}${mac ? ' or drag it in from Finder' : ''}${ok ? ', paste the words' : ''}${cover ? ', pick the cover' : ''}, and post.`,
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

      {targets && <>
        <p className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-muted">Words to post with it</p>
        <textarea value={text} onChange={(e) => setWords(e.target.value)} rows={3} aria-label="Words to post with it"
                  className="mt-1.5 w-full resize-y rounded-md border border-line bg-panel px-2 py-1.5 text-[12px] leading-snug text-zinc-100 outline-none focus:border-zinc-500" />
        <p className="mt-0.5 text-[11px] leading-snug text-muted">
          A start from where and when you filmed{targets.post.hashtags.length ? ', with a few hashtags' : ''} — change anything.
          {credit ? ' The music credit is added when you copy: the song’s licence asks for it.' : ''}</p>

        {targets.covers.length > 0 && <>
          <p className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-muted">Cover</p>
          <div className="mt-1.5 flex gap-1.5 overflow-x-auto pb-1">
            {targets.covers.map((c) => {
              const on = cover && Math.abs(cover.t - c.t) < 0.01
              return (
                <button key={c.t} type="button" onClick={() => pickCover(c.t)} disabled={picking !== null} aria-pressed={!!on}
                        title={`The frame at ${c.t.toFixed(1)} s`}
                        className={`shrink-0 overflow-hidden rounded-md border-2 ${on ? 'border-accent' : 'border-transparent hover:border-line'} ${picking === c.t ? 'opacity-50' : ''}`}>
                  <img src={c.url} alt="" loading="lazy" className={`${tall ? 'h-[92px] w-[52px]' : 'h-[52px] w-[92px]'} bg-black object-cover`} />
                </button>
              )
            })}
          </div>
          <p className="mt-0.5 text-[11px] leading-snug text-muted">
            {cover ? <>Saved “{cover.file}” beside the video — choose it as the cover on TikTok or Instagram.{' '}
              <a href={cover.url} download={cover.file} className="text-accent hover:underline">Download</a></>
              : 'Pick the still people see before they press play. It’s a frame of your video, captions and all.'}</p>
        </>}
      </>}

      <p className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-muted">Post it</p>
      {posting ? <YouTubePost job={job} cover={cover} onClose={() => setPosting(false)} /> : targets ? (<>
        <ul className="mt-1.5 space-y-1.5">
          {targets.platforms.map((p) => (
            <li key={p.id} className="flex items-start gap-2">
              <a href={p.url} target="_blank" rel="noopener noreferrer" onClick={() => go(p)} title={`Copies the words and opens ${p.where} in a new tab`}
                 className={`flex w-[136px] shrink-0 items-center justify-between rounded-lg px-3 py-1.5 text-[12px] ${p.ok ? 'bg-accent/20 text-zinc-100 hover:bg-accent/30' : 'border border-line text-zinc-300 hover:bg-raised'}`}>
                {p.name}<span aria-hidden className="text-[11px] text-muted">↗</span></a>
              <span className={`min-w-0 self-center text-[11px] leading-snug ${p.ok ? 'text-muted' : 'text-amber-200'}`}>
                {p.why ?? p.note ?? 'Fits.'}</span>
            </li>
          ))}
        </ul>
        {targets.other && onOther && (
          <button type="button" onClick={() => onOther(targets.other!.frame)}
                  className="mt-2 flex w-full items-center justify-between gap-2 rounded-lg border border-dashed border-line px-3 py-2 text-left hover:bg-raised">
            <span className="text-[12px] text-zinc-100">Make a {targets.other.label} version too
              <span className="block text-[11px] text-muted">For {targets.other.for} — the same edit, captions laid out again; any {targets.other.frame === 'tall'
                ? 'wide' : 'upright'} shots are cropped to fill the frame.</span></span>
            <span aria-hidden className="text-[16px] text-muted">{targets.other.frame === 'tall' ? '▯' : '▭'}</span>
          </button>
        )}
        {ytReady ? (
          <button type="button" onClick={() => setPosting(true)} className="mt-2 text-[12px] text-accent hover:underline">
            Or post it to your YouTube channel from here…</button>
        ) : ytReady === false && (
          <p className="mt-2 text-[11px] leading-snug text-muted">Posting to YouTube straight from VibeCut isn’t set up on this Mac yet (see “Posting to YouTube” in web/README.md).</p>
        )}
      </>) : <p className="mt-1 text-[11px] text-muted">Checking where it fits…</p>}

      <div className="mt-2 flex items-center gap-2">
        <button type="button" title="The words above, and the music credit its licence asks for"
                disabled={!caption}
                onClick={() => copy().then((ok) => { setSaid({ text: ok ? 'Words copied.' : 'Copy failed.' }); if (ok) record('caption') })}
                className="text-[11px] text-accent hover:underline disabled:text-zinc-600 disabled:no-underline">
          {caption ? `Copy the words${credit ? ' + credit' : ''}` : 'No words to copy'}</button>
      </div>
      {said && <p className="mt-1.5 text-[11px] leading-snug text-zinc-300">{said.text}
        {said.finder && <> <button type="button" onClick={() => api.exportReveal(job.id)} className="text-accent hover:underline">Show in Finder</button></>}</p>}
      <p className="mt-2 text-[10px] leading-snug text-zinc-500">VibeCut never posts by itself — only when you press Post.</p>
    </div>
  )
}
