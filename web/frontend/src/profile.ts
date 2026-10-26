export const PROFILE_KEY = 'vibecut.creator-profile.v1'
export const VIBES = ['Natural', 'Warm', 'Playful', 'Cinematic', 'Minimal', 'Dreamy'] as const
export const PLATFORMS = ['TikTok', 'Instagram', 'YouTube'] as const
export const PACES = ['Unhurried', 'Balanced', 'Quick'] as const
export const FONTS = ['Clean', 'Editorial', 'Rounded'] as const
export type CreatorProfile = {
  version: 1
  name: string
  /** names the profile (asked after an export); nothing is sent to it */
  email: string
  handle: string
  about: string
  goal: string
  platforms: string[]
  vibes: string[]
  pace: typeof PACES[number]
  font: typeof FONTS[number]
  color: string
  captionPosition: 'Middle' | 'Lower'
  avoid: string
  references: { url: string; note: string }[]
}
export const emptyProfile = (): CreatorProfile => ({
  version: 1, name: '', email: '', handle: '', about: '', goal: '', platforms: [], vibes: [],
  pace: 'Balanced', font: 'Clean', color: '#b9d9eb', captionPosition: 'Lower',
  avoid: '', references: [],
})

export const EMAIL = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$/

// the profile page's pacing words and the editor's pace (tempo.NAMES), one for one
export const PACE_WORDS: Record<string, typeof PACES[number]> = { fast: 'Quick', balanced: 'Balanced', calm: 'Unhurried' }

// logged out, the popup after an export asks for an account once in this browser (ProfileAsk.tsx)
export const ASKED_HERE = 'vibecut.profile-asked'
export function askedHere(): boolean {
  try { return window.localStorage.getItem(ASKED_HERE) === '1' } catch { return false }
}

export function safeReference(url: string): boolean {
  try { return ['https:', 'http:'].includes(new URL(url).protocol) } catch { return false }
}

// Stored data is untrusted: a stale or malformed profile must not break the editor.
export function decodeProfile(raw: string | null): CreatorProfile {
  if (!raw) return emptyProfile()
  const p = JSON.parse(raw)
  if (!p || p.version !== 1) throw new Error('This saved profile format is not supported.')
  const result = emptyProfile()
  for (const key of ['name', 'handle', 'about', 'goal', 'avoid'] as const) {
    if (typeof p[key] === 'string') result[key] = p[key].slice(0, key === 'name' || key === 'handle' ? 80 : 1000)
  }
  if (typeof p.email === 'string' && EMAIL.test(p.email.trim())) result.email = p.email.trim()
  result.platforms = PLATFORMS.filter(v => Array.isArray(p.platforms) && p.platforms.includes(v))
  result.vibes = VIBES.filter(v => Array.isArray(p.vibes) && p.vibes.includes(v))
  if (PACES.includes(p.pace)) result.pace = p.pace
  if (FONTS.includes(p.font)) result.font = p.font
  if (typeof p.color === 'string' && /^#[0-9a-f]{6}$/i.test(p.color)) result.color = p.color
  if (p.captionPosition === 'Middle') result.captionPosition = 'Middle'
  if (Array.isArray(p.references)) result.references = p.references.filter(
    (r: unknown): r is { url: string; note: string } => !!r && typeof r === 'object'
      && 'url' in r && typeof r.url === 'string' && r.url.length <= 2048 && safeReference(r.url)
      && 'note' in r && typeof r.note === 'string',
  ).slice(0, 10).map((r: { url: string; note: string }) => ({ url: r.url, note: r.note.slice(0, 500) }))
  return result
}

export function loadProfile(storage: Pick<Storage, 'getItem'>): { profile: CreatorProfile; error: string | null } {
  try { return { profile: decodeProfile(storage.getItem(PROFILE_KEY)), error: null } }
  catch { return { profile: emptyProfile(), error: 'Your saved profile could not be loaded. Saving will replace it with the details below.' } }
}

export function saveProfile(storage: Pick<Storage, 'setItem'>, profile: CreatorProfile): CreatorProfile {
  const clean = decodeProfile(JSON.stringify(profile))
  storage.setItem(PROFILE_KEY, JSON.stringify(clean))
  return clean
}
