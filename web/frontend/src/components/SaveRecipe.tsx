import { useEffect, useRef, useState } from 'react'
import { api, type Recipe, type RecipeDraft } from '../api'
import { Button, Dialog, inputCls } from '../ui'

// Save as my recipe (backend recipes.py): this edit's cut and dress, kept
// under a name and offered under "Cut it like" before the next Make. Like a
// preset in other editors: named here (the video's own name to start), the
// same name again replaces that one, renamed or deleted where it's picked.
export function SaveRecipe({ onClose, onSaved }: {
  onClose: () => void
  onSaved: (r: Recipe, replaced: boolean) => void
}) {
  const [draft, setDraft] = useState<RecipeDraft | null>(null)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const box = useRef<HTMLInputElement>(null)
  useEffect(() => {
    api.recipeDraft().then((d) => { setDraft(d); setName(d.name); window.setTimeout(() => box.current?.select(), 0) },
                          (e) => setError((e as Error).message))
  }, [])
  const clean = name.trim().replace(/\s+/g, ' ')
  const same = draft?.names.find((n) => n.toLowerCase() === clean.toLowerCase())
  const save = async () => {
    if (!clean || busy) return
    setBusy(true)
    setError(null)
    try {
      const r = await api.saveRecipe(clean)
      onSaved(r.recipe, r.replaced)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }
  return (
    <Dialog title="Save as my recipe" onClose={onClose} busy={busy} width={460}
            sub="Your next video can be cut and dressed like this one: pick it under Cut it like before Make my video."
            footer={<>
              <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
              <Button variant="primary" onClick={save} disabled={!draft || !clean || busy}>{busy ? 'Saving…' : same ? 'Replace it' : 'Save recipe'}</Button>
            </>}>
      <div className="space-y-3">
        <label className="block">
          <span className="font-serif text-[15px] text-zinc-200">Name</span>
          <input ref={box} value={name} maxLength={40} onChange={(e) => setName(e.target.value)} disabled={!draft || busy}
                 onKeyDown={(e) => { if (e.key === 'Enter') save() }} className={`mt-1 font-serif text-[16px] ${inputCls}`} />
        </label>
        {same && <p className="font-serif text-[14px] text-amber-200">This replaces your recipe “{same}”.</p>}
        {draft ? (
          <div>
            <p className="font-serif text-[15px] text-zinc-200">It keeps</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 font-serif text-[15px] leading-snug text-zinc-300">
              {draft.words.map((w) => <li key={w} className="first-letter:uppercase">{w}</li>)}
            </ul>
            <p className="mt-2 font-serif text-[14px] text-zinc-400">Only how it's cut and dressed is kept, never your clips. A video made from a recipe is free: AI doesn't plan it.</p>
          </div>
        ) : !error && <p className="font-serif text-[14px] text-zinc-400">Reading your edit…</p>}
        {error && <p className="font-serif text-[14px] text-rose-300">{error}</p>}
      </div>
    </Dialog>
  )
}
