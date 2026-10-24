import { useEffect, useState } from 'react'
import { api, type ShareCover, type YouTubePost as Post, type YouTubePrep, type YouTubeState } from '../api'
import type { ExportJob } from '../types'

// Post to the creator's own YouTube channel, from VibeCut. Every post goes
// through this screen: it shows the channel, the video, the title and who
// can see it, and nothing goes up until Post is pressed. The Post button
// carries a single-use code for this export (backend app.py), so the server
// refuses anything that didn't come from here.

const PRIVACY = [
  ['private', 'Only me', 'Private'],
  ['unlisted', 'Anyone with the link', 'Unlisted'],
  ['public', 'Everyone', 'Public'],
] as const

// `cover`: the one picked in the Share box now -- what this screen shows is what is sent
export function YouTubePost({ job, cover, onClose }: { job: ExportJob; cover: ShareCover | null; onClose: () => void }) {
  const [yt, setYt] = useState<YouTubeState | null>(null)
  const [signIn, setSignIn] = useState<string | null>(null)
  const [prep, setPrep] = useState<YouTubePrep | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [privacy, setPrivacy] = useState<string>('private')
  const [kids, setKids] = useState<boolean | null>(null)
  const [post, setPost] = useState<Post | null>(null)
  const [sending, setSending] = useState(false)

  const prepare = async () => {
    setError(null)
    try {
      const p = await api.youtubePrepare(job.id)
      setPrep(p)
      setTitle((t) => t || p.title)
      setDescription((d) => d || p.description)
    } catch (e) { setError((e as Error).message) }
  }

  // signed in? then the confirm screen; else Google's page, and wait for it
  useEffect(() => {
    let live = true
    let timer: number | undefined
    const look = async () => {
      try {
        const s = await api.youtube()
        if (!live) return
        setYt(s)
        if (s.connected) { setSignIn(null); prepare(); return }
        if (s.error) setError(s.error)
      } catch (e) { if (live) setError((e as Error).message) }
      if (live) timer = window.setTimeout(look, 1500)
    }
    api.youtube().then(async (s) => {
      if (!live) return
      setYt(s)
      if (s.connected) { prepare(); return }
      try { setSignIn((await api.youtubeConnect()).url) } catch (e) { setError((e as Error).message); return }
      timer = window.setTimeout(look, 1500)
    }).catch((e) => setError((e as Error).message))
    return () => { live = false; window.clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id])

  // the upload, once it's going
  useEffect(() => {
    if (!post || post.stage !== 'uploading') return
    const t = window.setTimeout(() => api.youtubePostStatus(post.id).then(setPost).catch(() => {}), 700)
    return () => window.clearTimeout(t)
  }, [post])

  const send = async () => {
    if (!prep) return
    setSending(true)
    setError(null)
    try {
      setPost(await api.youtubePost(job.id, { confirm: prep.confirm, title, description, privacy, made_for_kids: kids, cover_t: cover?.t ?? null }))
    } catch (e) {
      setError((e as Error).message)
      // a used or refused code can't be sent again: get a fresh one
      await prepare()
    } finally { setSending(false) }
  }

  const switchAccount = async () => {
    setPrep(null)
    setYt(await api.youtubeDisconnect())
    try { setSignIn((await api.youtubeConnect()).url) } catch (e) { setError((e as Error).message) }
  }

  const who = PRIVACY.find(([k]) => k === privacy)!
  const field = 'mt-1 w-full rounded-md border border-line bg-panel px-2 py-1 text-[12px] text-zinc-100 outline-none focus:border-zinc-500'
  const head = (
    <div className="flex items-baseline justify-between">
      <p className="font-serif text-[14px] text-zinc-100">Post to YouTube</p>
      {(!post || post.stage !== 'uploading') && <button type="button" onClick={onClose} className="text-[11px] text-muted hover:text-zinc-200">Back</button>}
    </div>
  )

  if (post) {
    const pct = Math.round(post.progress * 100)
    return (
      <div className="mt-2">
        {head}
        {post.stage === 'uploading' && <>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-800">
            <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${pct}%` }} />
          </div>
          <div className="mt-1.5 flex items-center justify-between text-[11px] text-muted">
            <span className="tabular-nums">Uploading “{post.title}”… {pct}%</span>
            <button type="button" onClick={() => api.youtubePostStop(post.id).then(setPost).catch(() => {})} className="hover:text-zinc-200">Stop</button>
          </div>
        </>}
        {post.stage === 'done' && <div className="mt-2 space-y-1.5 text-[12px] text-zinc-200">
          <p>On YouTube{post.privacy ? ` as ${post.privacy[0].toUpperCase()}${post.privacy.slice(1)}` : ''}. It can take a few minutes before it plays everywhere.</p>
          {post.cover && <p className={`text-[11px] ${post.cover === 'set' ? 'text-muted' : 'text-amber-200'}`}>
            {post.cover === 'set' ? 'Your cover is on it.' : post.cover}</p>}
          {post.privacy && post.privacy !== post.asked && <p className="text-[11px] text-amber-200">
            You asked for {post.asked}; YouTube set it to {post.privacy}. You can change that in YouTube Studio.</p>}
          <div className="flex gap-3 text-[12px]">
            {post.url && <a href={post.url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">Watch it ↗</a>}
            {post.studio && <a href={post.studio} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">Edit in YouTube Studio ↗</a>}
          </div>
        </div>}
        {post.stage === 'stopped' && <p className="mt-2 text-[12px] text-zinc-300">Stopped. Nothing went up to YouTube.</p>}
        {post.stage === 'error' && <p className="mt-2 text-[12px] text-rose-300">{post.error}</p>}
        {(post.stage === 'stopped' || post.stage === 'error') && <button type="button" onClick={() => setPost(null)}
          className="mt-2 rounded-lg border border-line px-3 py-1.5 text-[12px] text-zinc-200 hover:bg-raised">Back to the details</button>}
      </div>
    )
  }

  if (!yt) return <div className="mt-2">{head}<p className="mt-1 text-[11px] text-muted">Checking…</p></div>

  if (!yt.connected) return (
    <div className="mt-2">
      {head}
      <p className="mt-1 text-[12px] leading-snug text-zinc-300">Sign in with the Google account that owns your channel. VibeCut asks only to upload videos and to see your channel’s name, and keeps the sign-in on this Mac.</p>
      {signIn && <a href={signIn} target="_blank" rel="noopener noreferrer"
                    className="mt-2 inline-block rounded-lg bg-accent px-3 py-1.5 text-[12px] font-semibold text-accent-ink">Sign in with Google ↗</a>}
      {signIn && <p className="mt-1.5 text-[11px] text-muted">Waiting for you to finish on Google’s page…</p>}
      {error && <p className="mt-1.5 text-[12px] text-rose-300">{error}</p>}
    </div>
  )

  if (!prep) return (
    <div className="mt-2">{head}
      {error ? <p className="mt-1.5 text-[12px] text-rose-300">{error}</p> : <p className="mt-1 text-[11px] text-muted">Getting your channel…</p>}
    </div>
  )

  return (
    <div className="mt-2">
      {head}
      <div className="mt-2 flex items-center gap-2">
        {prep.channel.thumb && <img src={prep.channel.thumb} alt="" className="h-6 w-6 rounded-full" />}
        <span className="min-w-0 flex-1 truncate text-[12px] text-zinc-200">{prep.channel.title}</span>
        <button type="button" onClick={switchAccount} className="text-[11px] text-muted hover:text-zinc-200">Use another account</button>
      </div>

      <div className="mt-2 flex gap-2.5">
        <video src={`/api/export/${job.id}/file`} controls muted playsInline preload="metadata"
               className={`shrink-0 rounded-md bg-black ${job.size.h > job.size.w ? 'h-[150px] w-[84px]' : 'h-[84px] w-[150px]'} object-contain`} />
        <div className="min-w-0 flex-1">
          <label className="block text-[11px] text-muted">Title <span className="tabular-nums">{title.length}/100</span>
            <input value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} className={field} />
          </label>
          <label className="mt-1.5 block text-[11px] text-muted">Description
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className={`${field} resize-none`} />
          </label>
        </div>
      </div>

      <p className="mt-2 text-[11px] text-muted">Who can see it</p>
      <div className="mt-1 flex gap-1.5">
        {PRIVACY.map(([k, label]) => (
          <button key={k} type="button" onClick={() => setPrivacy(k)} aria-pressed={privacy === k}
                  className={`rounded-md px-2.5 py-1 text-[12px] ${privacy === k ? 'bg-accent font-semibold text-accent-ink' : 'border border-line text-zinc-200 hover:bg-raised'}`}>{label}</button>
        ))}
      </div>

      <p className="mt-2 text-[11px] text-muted">Is it made for kids? <span className="text-zinc-500">YouTube asks this of every video.</span></p>
      <div className="mt-1 flex gap-1.5">
        {([[false, 'No'], [true, 'Yes, it’s made for kids']] as const).map(([v, label]) => (
          <button key={label} type="button" onClick={() => setKids(v)} aria-pressed={kids === v}
                  className={`rounded-md px-2.5 py-1 text-[12px] ${kids === v ? 'bg-accent font-semibold text-accent-ink' : 'border border-line text-zinc-200 hover:bg-raised'}`}>{label}</button>
        ))}
      </div>

      {cover && <div className="mt-2 flex items-center gap-2">
        <img src={cover.url} alt="" className={`${job.size.h > job.size.w ? 'h-[54px] w-[30px]' : 'h-[30px] w-[54px]'} rounded bg-black object-cover`} />
        <span className="text-[11px] leading-snug text-muted">{prep.fit.name !== 'YouTube Shorts' ? 'Your cover goes with it.' : 'YouTube picks a Short’s cover in its own app; yours is saved beside the video.'}</span>
      </div>}
      {!cover && <p className="mt-2 text-[11px] text-muted">No cover picked — YouTube will choose a frame. Pick one under Cover first if you like.</p>}

      <p className={`mt-2 text-[11px] leading-snug ${prep.fit.ok ? 'text-muted' : 'text-amber-200'}`}>
        {prep.fit.why ?? prep.fit.note ?? (prep.fit.name === 'YouTube Shorts' ? 'It will be a Short: vertical and under 3 minutes.' : 'It will be a normal YouTube video.')}</p>

      <div className="mt-2.5 rounded-md bg-raised px-2.5 py-2 text-[12px] leading-snug text-zinc-200">
        This puts “{title.trim() || 'untitled'}” on <span className="font-medium">{prep.channel.title}</span>, seen by {who[1].toLowerCase()}.
        Nothing goes up until you press Post.
      </div>
      {error && <p className="mt-1.5 text-[12px] text-rose-300">{error}</p>}
      <div className="mt-2 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg px-3 py-1.5 text-[12px] text-muted hover:text-zinc-200">Cancel</button>
        <button type="button" onClick={send} disabled={sending || kids === null || !title.trim()}
                title={kids === null ? 'Say whether it’s made for kids first' : undefined}
                className="rounded-lg bg-accent px-3 py-1.5 text-[12px] font-semibold text-accent-ink disabled:opacity-30">
          {sending ? 'Starting…' : `Post to YouTube · ${who[2]}`}</button>
      </div>
    </div>
  )
}
