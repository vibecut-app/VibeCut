import type { Habit } from '../types'
import { api } from '../api'
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { emptyProfile, FONTS, loadProfile, PACES, PLATFORMS, safeReference, saveProfile, VIBES, type CreatorProfile as Profile } from '../profile'
import { Button, Confirm, Field, inputCls, Notice, Pills, Wordmark } from '../ui'

// Your profile: the things that stay the same across videos -- your name
// and handle (for name tags and end cards), your caption font, colour and
// placement (the default style of words on screen), and bookmarks of
// videos you like. Saved in this browser; no account.
//
// Honest about reach: today the editor reads the name, handle, font,
// colour and caption placement. Pace, vibes and bookmarks are kept for
// you but don't steer the edit yet.

export function CreatorProfile({ onClose }: { onClose: () => void }) {
  const [initial] = useState(() => {
    try { return loadProfile(window.localStorage) }
    catch { return { profile: emptyProfile(), error: 'Browser storage is unavailable. You can fill this in, but it cannot be saved here.' } }
  })
  const [profile, setProfile] = useState(initial.profile)
  const [saved, setSaved] = useState(initial.profile)
  const [error, setError] = useState<string | null>(initial.error)
  const [message, setMessage] = useState('')
  const [leaving, setLeaving] = useState(false)
  const [url, setUrl] = useState('')
  const [referenceNote, setReferenceNote] = useState('')
  const [referenceError, setReferenceError] = useState('')
  const heading = useRef<HTMLHeadingElement>(null)
  const dirty = JSON.stringify(profile) !== JSON.stringify(saved)
  const pendingReference = !!(url.trim() || referenceNote.trim())
  const unsaved = dirty || pendingReference
  useEffect(() => { heading.current?.focus() }, [])
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (unsaved) e.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [unsaved])
  const update = <K extends keyof Profile>(key: K, value: Profile[K]) => {
    setProfile(p => ({ ...p, [key]: value }))
    setMessage('')
  }
  const toggle = (key: 'platforms' | 'vibes', value: string) => update(key,
    profile[key].includes(value) ? profile[key].filter(v => v !== value) : [...profile[key], value])
  const store = () => {
    if (pendingReference) {
      setReferenceError('Add your reference below, or clear its fields before saving.')
      return
    }
    try {
      const next = saveProfile(window.localStorage, profile)
      setProfile(next); setSaved(next); setError(null); setMessage('Saved in this browser.'); setLeaving(false)
      // and beside the defaults on the server, so it follows you (cloud.py when configured)
      api.profilePut(next as unknown as Record<string, unknown>).then((r) => { if (r && (r as { cloud?: { on: boolean } }).cloud?.on) setMessage('Saved, and it follows you.') }).catch(() => {})
    } catch { setError('Could not save. Your changes are still here. Check browser storage permissions and try again.') }
  }
  const addReference = () => {
    const link = url.trim()
    if (!safeReference(link)) { setReferenceError('Enter a full link starting with https:// or http://.'); return }
    if (profile.references.some(r => r.url === link)) { setReferenceError('This reference is already saved.'); return }
    if (profile.references.length >= 10) { setReferenceError('You can save up to 10 references.'); return }
    update('references', [...profile.references, { url: link, note: referenceNote.trim() }])
    setUrl(''); setReferenceNote(''); setReferenceError('')
  }
  const back = () => { if (unsaved) setLeaving(true); else onClose() }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-ink">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-ink px-4">
        <Button variant="ghost" size="sm" onClick={back}>← Back</Button>
        <Wordmark />
        <span className="text-[13px] text-zinc-400">/ Your profile</span>
        <div className="flex-1" />
        <span className="hidden text-[11px] text-muted sm:inline" aria-live="polite">
          {error ? <span className="text-rose-300">{error}</span> : message || (unsaved ? 'Unsaved changes' : 'Stored in this browser · no account')}
        </span>
        <Button variant="primary" size="sm" onClick={store} disabled={!unsaved && !error}>Save</Button>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto">
        <form id="creator-form" onSubmit={e => { e.preventDefault(); store() }} className="mx-auto grid max-w-[1000px] gap-8 px-6 py-8 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="min-w-0 space-y-8">
            <div>
              <h1 ref={heading} tabIndex={-1} className="font-serif text-[30px] leading-tight text-zinc-100 outline-none">A little more you</h1>
              <p className="mt-1 text-[13px] text-zinc-400">What stays the same from video to video: your name on screen, your caption style, the videos you look up to.</p>
            </div>
            {error && <Notice tone="bad">{error}</Notice>}

            <Section n="01" title="You" text="Used for name tags and end cards.">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Your name"><input value={profile.name} maxLength={80} autoComplete="given-name" placeholder="What should we call you?" onChange={e => update('name', e.target.value)} className={inputCls} /></Field>
                <Field label="Handle"><input value={profile.handle} maxLength={80} placeholder="@yourname" autoCapitalize="none" onChange={e => update('handle', e.target.value)} className={inputCls} /></Field>
              </div>
              <Field label="What do you make?"><textarea value={profile.about} rows={2} maxLength={1000} placeholder="Little moments, weekend adventures, and places worth sharing…" onChange={e => update('about', e.target.value)} className={inputCls + ' resize-y'} /></Field>
              <Field label="Where you share"><Pills values={PLATFORMS} selected={profile.platforms} onPick={v => toggle('platforms', v)} /></Field>
            </Section>

            <Section n="02" title="Captions" text="The default font, colour and placement for titles, captions and name tags. Each video can still change them.">
              <Field label="Font"><Pills values={FONTS} selected={[profile.font]} onPick={v => update('font', v as Profile['font'])} /></Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Accent colour">
                  <div className="flex items-center gap-3">
                    <input type="color" aria-label="Accent colour" value={profile.color} onChange={e => update('color', e.target.value)} className="h-9 w-12 cursor-pointer rounded-md border border-line bg-ink" />
                    <span className="text-[12px] tabular-nums text-zinc-300">{profile.color.toUpperCase()}</span>
                  </div>
                </Field>
                <Field label="Caption placement"><Pills values={['Lower', 'Middle']} selected={[profile.captionPosition]} onPick={v => update('captionPosition', v as Profile['captionPosition'])} /></Field>
              </div>
            </Section>

            <Section n="03" title="Taste" text="Kept for you. Not yet read by the editor — say it in the brief for now.">
              <Field label="The feeling · pick a few"><Pills values={VIBES} selected={profile.vibes} onPick={v => toggle('vibes', v)} /></Field>
              <Field label="Pacing"><Pills values={PACES} selected={[profile.pace]} onPick={v => update('pace', v as Profile['pace'])} /></Field>
              <Field label="Things to avoid"><textarea value={profile.avoid} rows={2} maxLength={1000} placeholder="No heavy filters. Keep natural sound. Go easy on zooms." onChange={e => update('avoid', e.target.value)} className={inputCls + ' resize-y'} /></Field>
            </Section>

            <Section n="05" title="What VibeCut has learned about you" text="From what you cut, kept and switched off on more than one video. Each one is a small nudge, never a decision; switch any off here or with one tap on the video.">
              <Habits />
            </Section>
            <Section n="04" title="Videos you look up to" text="Bookmarks with a note. To actually borrow a video's feel, use Reference inside a project.">
              {profile.references.length > 0 && (
                <ul className="space-y-2">
                  {profile.references.map((r, i) => (
                    <li key={r.url} className="flex items-start gap-3 rounded-xl border border-line bg-raised px-3 py-2.5">
                      <div className="min-w-0 flex-1 break-words">
                        <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-[13px] text-zinc-100 underline underline-offset-2">{new URL(r.url).hostname} ↗</a>
                        <p className="mt-0.5 text-[12px] text-zinc-400">{r.note || r.url}</p>
                      </div>
                      <Button size="sm" variant="ghost" aria-label={`Remove reference ${i + 1}`} onClick={() => update('references', profile.references.filter((_, index) => index !== i))}>Remove</Button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Link"><input type="text" inputMode="url" value={url} maxLength={2048} placeholder="https://…" onChange={e => { setUrl(e.target.value); setReferenceError(''); setMessage('') }} className={inputCls} /></Field>
                <Field label="What do you like about it?"><input value={referenceNote} maxLength={500} placeholder="The quiet opening and handwritten captions." onChange={e => { setReferenceNote(e.target.value); setMessage('') }} className={inputCls} /></Field>
              </div>
              {referenceError && <Notice tone="bad">{referenceError}</Notice>}
              <Button onClick={addReference} disabled={profile.references.length >= 10}>+ Add reference <span className="text-muted">{profile.references.length}/10</span></Button>
            </Section>
          </div>

          <aside className="lg:sticky lg:top-0 lg:self-start">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">How your words will look</div>
            <div className="relative mt-2 aspect-[9/13] overflow-hidden rounded-xl border border-line bg-[linear-gradient(155deg,#4a4d55_0%,#2b3038_48%,#15181d_100%)]" style={{ '--signature': profile.color } as CSSProperties}>
              <div className={`absolute inset-x-4 text-center font-semibold leading-relaxed ${profile.captionPosition === 'Lower' ? 'bottom-[22%]' : 'top-[44%]'} ${profile.font === 'Editorial' ? 'font-serif text-[28px] font-normal' : profile.font === 'Rounded' ? 'text-[22px] [font-family:Nunito,ui-rounded,system-ui,sans-serif]' : 'text-[22px]'}`}>
                <span className="bg-black/70 px-2 py-0.5 text-[color:var(--signature)] [box-decoration-break:clone]">little moments,</span><br />
                <span className="bg-black/70 px-2 py-0.5 text-[color:var(--signature)] [box-decoration-break:clone]">worth keeping.</span>
              </div>
              <span className="absolute bottom-4 left-4 right-4 truncate text-[11px] text-zinc-300">{profile.handle || 'your next story'}</span>
            </div>
            <div className="mt-4 flex items-center gap-3">
              <span className="grid size-10 shrink-0 place-items-center rounded-full bg-zinc-700 font-serif text-[22px] text-zinc-100">{profile.name.trim().slice(0, 1).toUpperCase() || 'Y'}</span>
              <div className="min-w-0">
                <div className="truncate text-[14px] text-zinc-100">{profile.name.trim() || 'Your name'}</div>
                <div className="truncate text-[11px] text-muted">{profile.platforms.join(' · ') || 'Where you share'}</div>
              </div>
            </div>
            <dl className="mt-4 space-y-1.5 border-t border-line pt-3 text-[12px]">
              <div className="flex justify-between"><dt className="text-muted">Words</dt><dd className="text-zinc-200">{profile.font} · {profile.captionPosition.toLowerCase()}</dd></div>
              <div className="flex justify-between"><dt className="text-muted">Pacing</dt><dd className="text-zinc-200">{profile.pace}</dd></div>
              <div className="flex justify-between"><dt className="text-muted">References</dt><dd className="text-zinc-200">{profile.references.length}</dd></div>
            </dl>
            <a href="#/welcome" className="mt-6 block text-[12px] text-muted underline underline-offset-2 hover:text-zinc-100">About VibeCut</a>
          </aside>
        </form>
      </main>

      {leaving && (
        <Confirm title="Keep your changes?" text="Your latest changes haven’t been saved." action="Leave without saving" danger
                 onNo={() => setLeaving(false)} onYes={onClose} />
      )}
    </div>
  )
}

function Section({ n, title, text, children }: { n: string; title: string; text: string; children: ReactNode }) {
  return (
    <section className="border-t border-line pt-6">
      <header className="flex gap-3">
        <span className="pt-1 text-[11px] tabular-nums text-muted">{n}</span>
        <div>
          <h2 className="font-serif text-[22px] leading-tight text-zinc-100">{title}</h2>
          <p className="mt-0.5 text-[12px] text-zinc-400">{text}</p>
        </div>
      </header>
      <div className="mt-4 grid gap-4 pl-8">{children}</div>
    </section>
  )
}


function Habits() {
  const [list, setList] = useState<Habit[] | null>(null)
  const [phrases, setPhrases] = useState<string[]>([])
  useEffect(() => { api.habits().then((r) => { setList(r.habits); setPhrases(r.phrases) }).catch(() => setList([])) }, [])
  if (list === null) return <p className="text-[12px] text-muted">Looking…</p>
  if (!list.length && !phrases.length) return <p className="text-[12px] text-muted">Nothing yet. It takes the same thing on two videos.</p>
  return (
    <div className="space-y-2">
      {list.map((h) => (
        <label key={h.id} className="flex items-center gap-3 text-[13px] text-zinc-200">
          <input type="checkbox" checked={!h.off} onChange={async (e) => {
            const off = !e.target.checked
            await api.habitSwitch(h.id, off).catch(() => {})
            setList((l) => l && l.map((x) => (x.id === h.id ? { ...x, off } : x)))
          }} />
          <span className={h.off ? 'line-through text-muted' : ''}>{h.text.charAt(0).toUpperCase() + h.text.slice(1)}</span>
          <span className="text-[11px] text-muted">from {h.evidence.join(', ')} · used {h.used}×</span>
        </label>
      ))}
      {phrases.length > 0 && <p className="text-[12px] text-muted">Your own lines the writer learns from: {phrases.slice(0, 5).map((p) => `“${p}”`).join(', ')}</p>}
    </div>
  )
}
