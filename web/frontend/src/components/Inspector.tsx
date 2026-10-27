import { useEffect, useRef, useState, type ReactNode } from 'react'
import { CAPTION_FONTS, type CaptionFont } from '../captionFonts'
import type { SeqItem } from '../sequence'
import { dressOf, isDressed, KIND_META } from '../overlayDraw'
import { multiline, typable, wordsOf, wordsPatch } from '../captionWords'
import type { HeadingLook, JoinInfo, LookInfo, Overlay, OverlayPlace, OverlayStyle, ResourceKind, SoundStrip } from '../types'
import { Button, cx } from '../ui'
import { Icon, type IconName } from './icons'
import { CaptionAnimations, CaptionStyles, Transitions } from './StyleBars'
import { EffectTiles } from './Effects'
import { effectName } from '../effectView'
import { lineLabel, lineName } from '../overlayDraw'
import type { LineLook, LineRole } from '../types'

// The right-hand inspector of the edit screen (sarah, 2026-10-16: the layout
// of her reference picture). Six tabs: Edit (the clicked shot: trim, speed,
// turn, fit or fill; with nothing clicked, the whole video), Captions (the
// clicked caption's words, then one style and entrance for every caption),
// Effects (the clicked shot's effect, else every shot's; the transition at a cut),
// Audio (the shot's or a sound strip's volume and fades, and the music),
// Adjust (the look) and Graphic animations (graphics.py: pieces drawn over
// the video, Graphics.tsx). Clicking something on the timeline opens its tab.
// Every change is one undoable turn, sent when a slider is let go.

export type InspectorTab = 'edit' | 'captions' | 'effects' | 'audio' | 'adjust' | 'graphics'
type Patch = Record<string, unknown>

const TABS: { id: InspectorTab; icon: IconName; label: string }[] = [
  { id: 'edit', icon: 'scissors', label: 'Edit' },
  { id: 'captions', icon: 'cc', label: 'Captions' },
  { id: 'effects', icon: 'spark', label: 'Effects' },
  { id: 'audio', icon: 'music', label: 'Audio' },
  { id: 'adjust', icon: 'adjust', label: 'Adjust' },
  // sarah, 2026-10-19: "an extra tool on the right called graphic animations"
  { id: 'graphics', icon: 'shapes', label: 'Graphic animations' },
]

export type JoinPick = { join: JoinInfo; before: number | null; after: number | null; from: string | null; to: string | null }

export function Inspector(p: {
  tab: InspectorTab
  onTab: (t: InspectorTab) => void
  /** the clicked shot or empty space */
  item: SeqItem | null
  itemThumb: string | null
  clipName: string
  extracted: boolean
  strip: SoundStrip | null
  /** the clicked cut, else every cut shown on the first one; null when there are none */
  join: JoinPick | null
  joinPicked: boolean
  style: OverlayStyle
  captionsOn: boolean
  captionThumb: string | null
  captionSample: string
  /** the caption clicked on the picture or the timeline */
  caption: Overlay | null
  onCaptionEdit: (patch: { text?: string; sub?: string; look?: HeadingLook }, label: string) => void
  onCaptionDelete: () => void
  onCaptionAdd: () => void
  onCaptionWatch: () => void
  onCaptionDone: () => void
  onCaptionPlace: (place: OverlayPlace | null, label: string) => void
  looks: { id: string | null; all: LookInfo[] } | null
  music: ReactNode
  /** Length, tempo, frame, smoother cuts: the whole video's own controls */
  video: ReactNode
  /** the Graphic animations tab (Graphics.tsx) */
  graphics?: ReactNode
  onFix: (patch: Patch, label: string) => void
  onTrim: (edge: 'in' | 'out', to: number) => void
  onSplit: () => void
  /** the clip tools next to Split: the shot again right after itself, the frame under the playhead held */
  onDuplicate: () => void
  onFreeze: () => void
  /** the clicked shot's speed, turn, look, effect and sound settings, kept to put on another shot */
  onCopyFx: () => void
  onPasteFx: (() => void) | null
  onSwap: () => void
  onDelete: () => void
  onCloseGap: () => void
  onExtract: () => void
  onStrip: (patch: Patch, label: string) => void
  onStripDelete: () => void
  onCaptions: () => void
  onCaptionStyle: (patch: CaptionStylePatch, label: string) => void
  /** one line of the picked group (a title and the line under it), null = the whole group */
  line: LineRole | null
  onLine: (role: LineRole | null) => void
  onLineLook: (role: LineRole, look: LineLook | null, label: string) => void
  onJoin: (op: { kind: string; dur?: number; all?: boolean }, label: string) => void
  /** every shot's effect when they all share one (with no shot clicked), and a thumbnail to show effects on */
  allEffect: { effect: string | null; amount: number; thumb: string | null }
  onEffect: (patch: { effect?: string | null; effect_amount?: number }, all: boolean, label: string) => void
  onLook: (id: string, name: string) => void
  /** "Save to My resources": what's on the video now, kept in the folder (signed out: the sign-in card) */
  onSave: (kind: ResourceKind, why: string | null) => void
  /** what can be saved right now: null = ready, else what to do first (App works it out, for the folder too) */
  saveWhy: Record<ResourceKind, string | null>
}) {
  const it = p.item
  // A title with a line under it (or a caption with its place name) is a
  // group: each line can be picked and tuned on its own. A chapter title
  // has its own look, so it has no "every caption" to fall back to.
  const cap = p.caption
  const grouped = !!cap && (!!cap.sub || cap.kind === 'heading')
  const ownLook = cap?.kind === 'heading'
  const role: LineRole | null = cap && grouped ? p.line ?? (ownLook ? 'main' : null) : null
  const shot = it && it.kind === 'shot' ? it : null
  // at the top of what it saves, so it's seen without scrolling past the tiles
  const save = (kind: ResourceKind, what: string) => (
    <div><SaveChip what={what} ready={!p.saveWhy[kind]} onClick={() => p.onSave(kind, p.saveWhy[kind])} /></div>
  )
  return (
    <aside className="flex min-h-0 min-w-0 flex-1 flex-col">
      <nav className="flex shrink-0 gap-0.5 border-b border-line px-2 pt-2" role="tablist">
        {TABS.filter((t) => t.id !== 'adjust' || p.looks?.all.length).map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={p.tab === t.id} onClick={() => p.onTab(t.id)}
                  // a two-word name (Graphic animations) goes on two tighter lines
                  className={cx('-mb-px flex min-w-0 flex-1 flex-col items-center gap-1 rounded-t-lg border-b-2 px-1 pb-2 pt-2 text-center font-serif',
                    t.label.includes(' ') ? 'text-[13.5px] leading-[1.1]' : 'text-[15px]',
                    p.tab === t.id ? 'border-accent bg-accent/8 text-accent' : 'border-transparent text-zinc-300 hover:text-zinc-100')}>
            <Icon name={t.icon} size={22} />
            {t.label}
          </button>
        ))}
      </nav>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5">
        {p.tab === 'edit' && (shot ? <>
          <Section title="Clip">
            <div className="flex items-center gap-3">
              <span className="h-14 w-20 shrink-0 overflow-hidden rounded-lg bg-black">
                {p.itemThumb && <img src={p.itemThumb} alt="" className="size-full object-cover" />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate font-serif text-[16px] text-zinc-100">Shot {shot.n} · {p.clipName}</div>
                <div className="font-serif text-[15px] tabular-nums text-zinc-300">
                  {mmss(shot.src_start)} – {mmss(shot.src_end)} ({(shot.seq_end - shot.seq_start).toFixed(1)}s)</div>
              </div>
              <Button size="sm" onClick={p.onSwap} title="Put a different shot in its place">Replace</Button>
            </div>
          </Section>
          {shot.freeze ? (
            <Slider label="Hold for" value={Math.round((shot.seq_end - shot.seq_start) * 10) / 10} min={0.5} max={10} step={0.1} unit=" s"
                    onCommit={(v) => p.onTrim('out', shot.src_start + v)} />
          ) : <>
            <Section title="Trim"><TrimBar item={shot} thumb={p.itemThumb} onTrim={p.onTrim} /></Section>
            <SpeedLine speed={shot.speed ?? 1} onFix={(x) => p.onFix({ speed: x }, x === 1 ? `You put shot ${shot.n} back to normal speed` : `You set shot ${shot.n} to ${x}×`)} />
            <Line label="Reverse">
              <Segmented options={[['off', 'Forwards'], ['on', 'Backwards']]} value={shot.reverse ? 'on' : 'off'}
                         onPick={(v) => (v === 'on') !== !!shot.reverse && p.onFix({ reverse: v === 'on' }, v === 'on' ? `Shot ${shot.n} plays backwards` : `Shot ${shot.n} plays forwards again`)} />
            </Line>
          </>}
          <Line label="Rotate">
            <IconChip label="Turn left" icon="turnL" onClick={() => p.onFix({ rotate: ((shot.rotate ?? 0) + 270) % 360 }, `You turned shot ${shot.n} left`)} />
            <IconChip label="Turn right" icon="turnR" onClick={() => p.onFix({ rotate: ((shot.rotate ?? 0) + 90) % 360 }, `You turned shot ${shot.n} right`)} />
            <span className="flex-1" />
            <Value>{shot.rotate ?? 0}°</Value>
          </Line>
          <Line label="Mirror">
            <Segmented options={[['off', 'Off'], ['on', 'Mirrored']]} value={shot.mirror ? 'on' : 'off'}
                       onPick={(v) => (v === 'on') !== !!shot.mirror && p.onFix({ mirror: v === 'on' }, `You ${v === 'on' ? 'mirrored' : 'unmirrored'} shot ${shot.n}`)} />
          </Line>
          <Line label="Crop & zoom">
            <Segmented options={[['fit', 'Fit'], ['fill', 'Fill']]} value={shot.fill ? 'fill' : 'fit'}
                       onPick={(v) => (v === 'fill') !== !!shot.fill && p.onFix({ fill: v === 'fill' }, v === 'fill' ? `Shot ${shot.n} fills the frame` : `Shot ${shot.n} shows its whole picture`)} />
          </Line>
          <div className="flex flex-wrap gap-2 pt-1">
            <Chip onClick={p.onSplit}><Icon name="split" size={17} /> Split at the playhead</Chip>
            <Chip onClick={p.onDuplicate} title="The same shot again, right after this one (⌘D)"><Icon name="copy" size={17} /> Duplicate</Chip>
            {!shot.freeze && <Chip onClick={p.onFreeze} title="Hold the frame under the playhead for 3 seconds"><Icon name="freeze" size={17} /> Freeze frame</Chip>}
            <Chip onClick={p.onCopyFx} title="Keep this shot's speed, turn, crop, effect and sound settings (⌥⌘C)"><Icon name="adjust" size={17} /> Copy settings</Chip>
            <Chip onClick={() => p.onPasteFx?.()} disabled={!p.onPasteFx} title="Give this shot the settings you copied (⌥⌘V)"><Icon name="paste" size={17} /> Paste settings</Chip>
            <SaveChip what="settings" ready={!p.saveWhy.shot} onClick={() => p.onSave('shot', p.saveWhy.shot)} />
            <Chip danger onClick={p.onDelete}><Icon name="trash" size={17} /> Delete</Chip>
            {!!(shot.rotate || shot.fill || shot.mirror) && <Chip onClick={() => p.onFix({ rotate: 0, fill: false, mirror: false }, `You put shot ${shot.n} back as filmed`)}>Back to as filmed</Chip>}
          </div>
        </> : it ? (
          <Section title={`Empty space · ${(it.seq_end - it.seq_start).toFixed(1)}s`}>
            <Button variant="primary" onClick={p.onCloseGap}>Close up this empty space</Button>
          </Section>
        ) : <>
          <Section title="Your video">{p.video}</Section>
          <Hint>Click a shot on the timeline to trim it, change its speed, turn it or crop it.</Hint>
        </>)}

        {p.tab === 'captions' && <>
          {p.caption && <CaptionWords key={p.caption.id} o={p.caption} onEdit={p.onCaptionEdit} onDelete={p.onCaptionDelete}
                                      onWatch={p.onCaptionWatch} onDone={p.onCaptionDone} onPlace={p.onCaptionPlace} />}
          {!p.caption && <>
            <Line label="Captions">
              <Segmented options={[['off', 'Off'], ['on', 'On']]} value={p.captionsOn ? 'on' : 'off'}
                         onPick={(v) => (v === 'on') !== p.captionsOn && p.onCaptions()} />
            </Line>
            <Button onClick={p.onCaptionAdd}>+ Add a caption at the playhead</Button>
          </>}
          {cap && grouped && (
            <Line label="Change">
              <Segmented options={[...(ownLook ? [] : [['all', 'Every caption'] as [string, string]]),
                                   ...(['main', 'sub'] as LineRole[]).filter((r) => r === 'main' || cap.sub).map((r) => [r, lineLabel(cap, r)] as [string, string])]}
                         value={role ?? 'all'} onPick={(v) => p.onLine(v === 'all' ? null : v as LineRole)} />
            </Line>
          )}
          {cap && role ? <LineLookPanel key={cap.id + role} o={cap} role={role} style={p.style} onLook={(look, label) => p.onLineLook(role, look, label)} /> : <>
          {p.captionsOn ? <>
            {save('caption', 'caption look')}
            <Section title={p.caption ? 'Font of every caption' : 'Font'}>
              <CaptionFonts value={p.style.typeface ?? null}
                            onPick={(f) => p.onCaptionStyle({ typeface: f?.id ?? null }, f ? `The captions are in ${f.name}` : 'The captions are back to their own font')} />
            </Section>
            <Section title={p.caption ? 'Colour of every caption' : 'Colour'}>
              <CaptionColours value={p.style.text_color ?? null}
                              onPick={(c) => p.onCaptionStyle({ text_color: c }, c ? 'You changed the colour of the captions' : 'The captions are back to their automatic colour')} />
            </Section>
            <CaptionDress style={p.style} onPick={p.onCaptionStyle} />
            <Section title="Word art"><CaptionStyles style={p.style} thumb={p.captionThumb} onPick={p.onCaptionStyle} /></Section>
            <Section title={p.caption ? 'Animation of every caption' : 'Animation'}>
              {save('animation', 'animation')}
              <CaptionAnimations style={p.style} thumb={p.captionThumb} sample={p.captionSample} onPick={p.onCaptionStyle} />
            </Section>
            {!p.caption && <Hint>One style for every caption. Click a caption on the picture or the timeline to change its words.</Hint>}
          </> : <Hint>Turn captions on to put the time and place of each moment on the video.</Hint>}
          </>}
        </>}

        {p.tab === 'effects' && <>
          {!p.joinPicked && (shot ? (
            <Section title={`Effect on shot ${shot.n}`}>
              {save('effect', 'effect')}
              <EffectTiles n={shot.n} effect={shot.effect ?? null} amount={shot.effect_amount ?? 1} thumb={p.itemThumb}
                           onPick={(patch, label) => p.onEffect(patch, false, label)}
                           onAll={() => p.onEffect({ effect: shot.effect ?? null, effect_amount: shot.effect_amount ?? 1 }, true,
                             shot.effect ? `Every shot now has ${effectName(shot.effect)}` : 'You took the effects off every shot')} />
            </Section>
          ) : (
            <Section title="Effect on every shot">
              <Hint>Or click a shot on the timeline to give just that shot an effect.</Hint>
              {save('effect', 'effect')}
              <EffectTiles n={null} effect={p.allEffect.effect} amount={p.allEffect.amount} thumb={p.allEffect.thumb}
                           onPick={(patch, label) => p.onEffect(patch, true, label)} onAll={() => {}} />
            </Section>
          ))}
          {p.join ? (
            <Section title={p.joinPicked ? `The cut from shot ${p.join.before} to shot ${p.join.after}` : 'Transition at every cut'}>
              {!p.joinPicked && <Hint>Or click the dot between two shots on the timeline to change just that cut.</Hint>}
              {save('transition', 'transition')}
              <Transitions {...p.join} before={p.joinPicked ? p.join.before : null} after={p.joinPicked ? p.join.after : null} onPick={p.onJoin} />
            </Section>
          ) : <Hint>Transitions go between two shots. Your edit has no cuts yet.</Hint>}
        </>}

        {p.tab === 'audio' && (p.strip?.voice ? (
          <Section title="Your voice">
            <Hint>Recorded over your video. The music goes quieter while you talk. Drag the strip on the timeline to move it.</Hint>
            <SoundLines gain={p.strip.gain} mute={p.strip.mute} fadeIn={p.strip.fade_in ?? 0} fadeOut={p.strip.fade_out ?? 0}
                        onFix={(x, what) => p.onStrip(x, `You ${what} on your voice`)} />
            <div className="pt-1"><Chip danger onClick={p.onStripDelete}><Icon name="trash" size={17} /> Delete this recording</Chip></div>
          </Section>
        ) : p.strip ? (
          <Section title={`Sound of shot ${p.strip.n ?? ''}`}>
            <Hint>It sits on its own strip under the picture. Drag the strip on the timeline to move it.</Hint>
            <SoundLines gain={p.strip.gain} mute={p.strip.mute} fadeIn={p.strip.fade_in ?? 0} fadeOut={p.strip.fade_out ?? 0}
                        onFix={(x, what) => p.onStrip(x, `You ${what} on the sound of shot ${p.strip!.n ?? ''}`)} />
            <div className="pt-1"><Chip danger onClick={p.onStripDelete}><Icon name="trash" size={17} /> Delete this sound</Chip></div>
          </Section>
        ) : shot ? (
          <Section title={`Sound of shot ${shot.n}`}>
            {p.extracted
              ? <Hint>This shot's sound is on its own strip under the picture. Click the strip to change it.</Hint>
              : <>
                <SoundLines gain={shot.gain ?? 1} mute={!!shot.mute} fadeIn={shot.fade_in ?? 0} fadeOut={shot.fade_out ?? 0}
                            onFix={(x, what) => p.onFix(x, `You ${what} on shot ${shot.n}`)} />
                <div className="pt-1"><Chip onClick={p.onExtract}>Take the sound off</Chip></div>
              </>}
          </Section>
        ) : <Section title="Music">{p.music}{!p.saveWhy.song && save('song', 'song')}<Hint>Click a shot on the timeline to change its own sound.</Hint></Section>)}

        {p.tab === 'graphics' && p.graphics}

        {p.tab === 'adjust' && p.looks && (
          <Section title="Look">
            <div className="flex flex-col gap-2">
              {p.looks.all.map((l) => (
                <button key={l.id} type="button" onClick={() => l.id !== p.looks!.id && p.onLook(l.id, l.name)}
                        className={cx('flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left',
                          l.id === p.looks!.id ? 'border-accent bg-accent/8' : 'border-line hover:bg-raised')}>
                  <span className="flex shrink-0 overflow-hidden rounded-md ring-1 ring-zinc-800">
                    {l.palette.slice(0, 4).map((c) => <span key={c} className="h-8 w-3" style={{ background: c }} />)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={cx('block font-serif text-[16px]', l.id === p.looks!.id ? 'text-accent' : 'text-zinc-100')}>{l.name}</span>
                    <span className="block truncate font-serif text-[15px] text-zinc-300">{l.line}</span>
                  </span>
                  {l.id === p.looks!.id && <Icon name="check" className="shrink-0 text-accent" />}
                </button>
              ))}
            </div>
            <Hint>The look sets the colour, the captions' type and how cuts move. Colour shows in the export.</Hint>
          </Section>
        )}
      </div>
    </aside>
  )
}

// The clicked caption's own words. One undoable turn when the box is left
// or Enter is pressed; Escape puts the words back.
function CaptionWords({ o, onEdit, onDelete, onWatch, onDone, onPlace }: {
  o: Overlay
  onEdit: (patch: { text?: string; sub?: string; look?: HeadingLook }, label: string) => void
  onDelete: () => void; onWatch: () => void; onDone: () => void
  onPlace: (place: OverlayPlace | null, label: string) => void
}) {
  // where it sits now: dragged by hand, else its usual spot (the drawing
  // still pulls it inside the safe area)
  const here: OverlayPlace = o.place ?? { x: 0.5, y: o.pos.startsWith('top') ? 0.2 : o.pos === 'center' ? 0.5 : 0.8, scale: 1 }
  const row = here.y < 0.35 ? 'top' : here.y > 0.65 ? 'bottom' : 'middle'
  const name = KIND_META[o.kind].label
  // one box, the lines as they read on the picture (captionWords.ts)
  const shown = wordsOf(o)
  const commit = (v: string) => {
    const patch = wordsPatch(o, v)
    if (patch) onEdit(patch, `You changed the words of the ${name.toLowerCase()}`)
  }
  return (
    <Section title={`This ${name.toLowerCase()} · ${mmss(o.start)}`}>
      {typable(o) && <WordsBox key={o.id + shown} value={shown} lines={multiline(o)} onCommit={commit} />}
      {o.kind === 'heading' && (
        // a chapter title has its own look; the line under it stays plain
        <Line label="Title look">
          <Segmented options={HEADING_LOOKS} value={o.look ?? 'spaced'}
                     onPick={(v) => v !== o.look && onEdit({ look: v as HeadingLook }, 'You changed the chapter title\'s look')} />
        </Line>
      )}
      <div className="flex flex-wrap gap-2 pt-1">
        <Chip onClick={onWatch}><Icon name="play" size={17} /> See it play</Chip>
        <Chip danger onClick={onDelete}><Icon name="trash" size={17} /> Delete</Chip>
        <Chip onClick={onDone}>Done</Chip>
      </div>
      <Line label="Place">
        <Segmented options={[['top', 'Top'], ['middle', 'Middle'], ['bottom', 'Bottom']]} value={row}
                   onPick={(v) => v !== row && onPlace({ x: 0.5, y: v === 'top' ? 0.2 : v === 'middle' ? 0.5 : 0.8, scale: here.scale },
                     `You moved the ${name.toLowerCase()} to the ${v}`)} />
      </Line>
      <Slider label="Size" value={Math.round(here.scale * 100)} min={40} max={300} step={10} unit="%"
              onCommit={(v) => onPlace({ ...here, scale: v / 100 }, `You made the ${name.toLowerCase()} ${v > here.scale * 100 ? 'bigger' : 'smaller'}`)} />
      <Hint>On the picture, drag it anywhere, drag a corner to size it, or click it again to type its words there.</Hint>
      {o.place && <Chip onClick={() => onPlace(null, `You put the ${name.toLowerCase()} back in its usual place`)}>Put it back in its usual place</Chip>}
    </Section>
  )
}

const HEADING_LOOKS: [string, string][] = [['spaced', 'Spaced'], ['script', 'Script'], ['serif', 'Serif'], ['bold', 'Bold']]

// The captions' colour. Automatic reads the footage behind each caption and
// picks what stands out; a picked colour is kept, with an edge or glow so it
// still reads. One undoable turn per pick.
const TEXT_COLOURS: [string, string][] = [['#ffffff', 'White'], ['#fff3d6', 'Cream'], ['#ffd84d', 'Yellow'], ['#ff9eb5', 'Pink'],
  ['#7fd0ff', 'Sky blue'], ['#8fe3b0', 'Mint'], ['#ff7a59', 'Coral'], ['#141414', 'Black']]
// outlines, shadows and backgrounds: true black first, the way editors offer them
const EDGE_COLOURS: [string, string][] = [['#000000', 'Black'], ['#ffffff', 'White'], ['#ffd84d', 'Yellow'], ['#ff9eb5', 'Pink'],
  ['#ff4d6d', 'Red'], ['#7fd0ff', 'Sky blue'], ['#8fe3b0', 'Mint'], ['#7b5cff', 'Purple']]

export type CaptionStylePatch = Partial<Pick<OverlayStyle, 'template' | 'enter' | 'text_color' | 'typeface' | 'outline' | 'shadow' | 'backdrop' | 'thick'>>

// Outline, shadow, background box and letter weight as plain controls, the
// way CapCut's text panel has them (sarah, 2026-10-18: "for the normal
// adjustments you dont have to have a video background"). Each starts from
// what the captions have now; a slider is one undoable turn when let go.
function CaptionDress({ style, onPick }: { style: OverlayStyle; onPick: (patch: CaptionStylePatch, label: string) => void }) {
  const d = dressOf(style)
  const pc = (x: number) => Math.round(x * 100)
  const onOff = (on: boolean, flip: (on: boolean) => void) => (
    <Segmented options={[['off', 'Off'], ['on', 'On']]} value={on ? 'on' : 'off'} onPick={(v) => (v === 'on') !== on && flip(v === 'on')} />
  )
  const ol = d.outline, sh = d.shadow, bd = d.backdrop
  return <>
    <Section title="Outline">
      {onOff(ol.width > 0, (on) => onPick({ outline: { ...ol, width: on ? 0.12 : 0 } }, on ? 'The captions have an outline' : 'The captions have no outline'))}
      {ol.width > 0 && <>
        <CaptionColours auto={false} value={ol.color} onPick={(c) => c && onPick({ outline: { ...ol, color: c } }, 'You changed the outline colour')} />
        <Slider label="Thickness" value={pc(ol.width)} min={1} max={40} step={1} unit=""
                onCommit={(x) => onPick({ outline: { ...ol, width: x / 100 } }, 'You changed how thick the outline is')} />
      </>}
    </Section>
    <Section title="Shadow">
      {onOff(sh.opacity > 0, (on) => onPick({ shadow: { ...sh, opacity: on ? 0.7 : 0 } }, on ? 'The captions have a shadow' : 'The captions have no shadow'))}
      {sh.opacity > 0 && <>
        <CaptionColours auto={false} value={sh.color} onPick={(c) => c && onPick({ shadow: { ...sh, color: c } }, 'You changed the shadow colour')} />
        <Slider label="Strength" value={pc(sh.opacity)} min={10} max={100} step={5} unit="%"
                onCommit={(x) => onPick({ shadow: { ...sh, opacity: x / 100 } }, 'You changed how strong the shadow is')} />
        <Slider label="Softness" value={pc(sh.blur)} min={0} max={150} step={5} unit=""
                onCommit={(x) => onPick({ shadow: { ...sh, blur: x / 100 } }, 'You changed how soft the shadow is')} />
        <Slider label="Distance" value={pc(sh.dist)} min={0} max={40} step={1} unit=""
                onCommit={(x) => onPick({ shadow: { ...sh, dist: x / 100 } }, 'You moved the shadow')} />
      </>}
    </Section>
    <Section title="Background">
      {onOff(bd.opacity > 0, (on) => onPick({ backdrop: { ...bd, opacity: on ? 0.85 : 0 } }, on ? 'The captions sit on a background' : 'The captions have no background'))}
      {bd.opacity > 0 && <>
        <CaptionColours auto={false} value={bd.color} onPick={(c) => c && onPick({ backdrop: { ...bd, color: c } }, 'You changed the background colour')} />
        <Slider label="Opacity" value={pc(bd.opacity)} min={10} max={100} step={5} unit="%"
                onCommit={(x) => onPick({ backdrop: { ...bd, opacity: x / 100 } }, 'You changed how see-through the background is')} />
        <Slider label="Roundness" value={pc(bd.round)} min={0} max={50} step={1} unit=""
                onCommit={(x) => onPick({ backdrop: { ...bd, round: x / 100 } }, 'You changed how round the background is')} />
      </>}
    </Section>
    <Section title="Boldness">
      <Slider label="Letters" value={pc(d.thick)} min={0} max={15} step={1} unit=""
              onCommit={(x) => onPick({ thick: x / 100 }, x ? 'You made the letters bolder' : 'The letters are back to their usual weight')} />
    </Section>
    {isDressed(style) && <div><Chip onClick={() => onPick({ outline: null, shadow: null, backdrop: null, thick: null }, 'Outline, shadow and background are back to the style\'s own')}>
      Back to the style's own outline, shadow and background</Chip></div>}
  </>
}

// Each font shown in its own letters on a dark tile, the way it will sit on
// the footage; one tap sets it for every caption (one font per video).
function CaptionFonts({ value, onPick }: { value: string | null; onPick: (f: CaptionFont | null) => void }) {
  const tile = (on: boolean) => cx('flex h-14 min-w-0 items-center justify-center rounded-lg border px-2 text-center',
    on ? 'border-accent ring-2 ring-accent ring-offset-2 ring-offset-panel' : 'border-black/15 hover:brightness-125')
  return (
    <div className="grid grid-cols-2 gap-2.5">
      <button type="button" aria-pressed={!value} onClick={() => value && onPick(null)}
              className={cx('flex h-14 items-center justify-center rounded-lg border px-2 font-serif text-[16px]',
                !value ? 'border-accent bg-accent text-accent-ink' : 'border-line bg-panel text-zinc-100 hover:bg-raised')}>Style's own</button>
      {CAPTION_FONTS.map((f) => (
        <button key={f.id} type="button" title={f.name} aria-label={f.name} aria-pressed={value === f.id}
                onClick={() => value !== f.id && onPick(f)} className={tile(value === f.id)} style={{ background: '#1d1d22' }}>
          <span className="leading-[1.1] text-white"
                style={{ fontFamily: f.family, fontWeight: f.weight, fontSize: Math.round((f.name.length > 12 ? 16 : 19) * f.size) }}>{f.name}</span>
        </button>
      ))}
    </div>
  )
}

function CaptionColours({ value, onPick, auto = true }: { value: string | null; onPick: (c: string | null) => void; auto?: boolean }) {
  const COLOURS = auto ? TEXT_COLOURS : EDGE_COLOURS
  const [own, setOwn] = useState(value ?? '#ffffff')
  // the picker's native change fires once, when it closes; React's onChange fires on every drag
  const ref = useRef<HTMLInputElement>(null)
  const pick = useRef(onPick)
  pick.current = onPick
  useEffect(() => {
    const el = ref.current
    const done = () => el && el.value !== value && pick.current(el.value)
    el?.addEventListener('change', done)
    return () => el?.removeEventListener('change', done)
  }, [value])
  const custom = !!value && !COLOURS.some(([c]) => c === value)
  return (
    <div className="flex flex-wrap items-center gap-2.5">
      {auto && <button type="button" aria-pressed={!value} onClick={() => value && onPick(null)}
              className={cx('rounded-lg border px-3 py-1.5 font-serif text-[15px]',
                !value ? 'border-accent bg-accent text-accent-ink' : 'border-line bg-panel text-zinc-100 hover:bg-raised')}>Automatic</button>}
      {COLOURS.map(([c, name]) => (
        <button key={c} type="button" title={name} aria-label={name} aria-pressed={value === c} onClick={() => value !== c && onPick(c)}
                className={cx('size-9 shrink-0 rounded-full border border-black/15', value === c && 'ring-2 ring-accent ring-offset-2 ring-offset-panel')}
                style={{ background: c }} />
      ))}
      <label title="Any colour" className={cx('relative inline-flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 font-serif text-[15px]',
        custom ? 'border-accent text-accent' : 'border-line bg-panel text-zinc-100 hover:bg-raised')}>
        <span className="size-5 rounded-full border border-black/15" style={{ background: custom ? value! : 'conic-gradient(#ff6b6b, #ffd84d, #8fe3b0, #7fd0ff, #c49bff, #ff6b6b)' }} />
        Other…
        <input ref={ref} type="color" value={custom ? value! : own} onChange={(e) => setOwn(e.target.value)}
               className="absolute inset-0 cursor-pointer opacity-0" />
      </label>
    </div>
  )
}

function WordsBox({ value, lines, onCommit }: { value: string; lines: boolean; onCommit: (v: string) => void }) {
  const [v, setV] = useState(value)   // keyed on value by the caller: a new value remounts
  return (
    <textarea value={v} maxLength={200} aria-label="Words" rows={Math.max(2, v.split('\n').length)} onChange={(e) => setV(e.target.value)}
              onBlur={() => v !== value && onCommit(v)}
              onKeyDown={(e) => {
                e.stopPropagation()   // typing must not split shots or play the video
                // Enter starts a new line where there can be one, like any text box; leaving the box saves
                if (e.key === 'Enter' && (!lines || e.metaKey || e.ctrlKey)) { e.preventDefault(); (e.target as HTMLTextAreaElement).blur() }
                if (e.key === 'Escape') { setV(value); setTimeout(() => (e.target as HTMLTextAreaElement).blur()) }
              }}
              className="block w-full resize-none rounded-lg border border-line bg-panel px-3 py-2 font-serif text-[17px] leading-snug text-zinc-100 outline-none focus:border-accent" />
  )
}

const mmss = (t: number) => {
  const m = Math.floor(t / 60)
  return `${String(m).padStart(2, '0')}:${(t - m * 60).toFixed(1).padStart(4, '0')}`
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="font-serif text-[18px] font-medium text-zinc-100">{title}</h3>
      {children}
    </section>
  )
}

function Hint({ children }: { children: ReactNode }) {
  return <p className="font-serif text-[15px] leading-snug text-zinc-300">{children}</p>
}

function Line({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-24 shrink-0 font-serif text-[16px] text-zinc-100">{label}</span>
      <div className="flex min-w-0 flex-1 items-center gap-2">{children}</div>
    </div>
  )
}

function Value({ children }: { children: ReactNode }) {
  return <span className="min-w-[4rem] shrink-0 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-center font-serif text-[15px] tabular-nums text-zinc-100">{children}</span>
}

function Segmented({ options, value, onPick }: { options: [string, string][]; value: string; onPick: (v: string) => void }) {
  return (
    <div className="flex flex-1 rounded-lg bg-raised p-0.5">
      {options.map(([id, name]) => (
        <button key={id} type="button" aria-pressed={value === id} onClick={() => onPick(id)}
                className={cx('flex-1 rounded-md px-3 py-1.5 font-serif text-[15px]',
                  value === id ? 'bg-panel text-accent shadow-sm' : 'text-zinc-300 hover:text-zinc-100')}>{name}</button>
      ))}
    </div>
  )
}

function IconChip({ icon, label, onClick }: { icon: IconName; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} title={label} aria-label={label}
            className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-panel text-zinc-100 hover:bg-raised">
      <Icon name={icon} size={18} />
    </button>
  )
}

/** A labelled slider with its value beside it; one turn when let go. */
export function Slider({ label, value, min, max, step, unit, disabled, onCommit }: {
  label: string; value: number; min: number; max: number; step: number; unit: string; disabled?: boolean
  onCommit: (v: number) => void
}) {
  const [drag, setDrag] = useState<number | null>(null)
  const v = drag ?? value
  const commit = () => {
    setDrag(null)
    const r = Math.round(v / step) * step
    const x = Math.round(r * 100) / 100
    if (Math.abs(x - value) > 1e-6) onCommit(x)
  }
  return (
    <label className={cx('flex items-center gap-3', disabled && 'opacity-40')}>
      <span className="w-24 shrink-0 font-serif text-[16px] text-zinc-100">{label}</span>
      <input type="range" min={min} max={max} step={step} value={v} disabled={disabled} className="min-w-0 flex-1 accent-[#1f5f8b]"
             onChange={(e) => setDrag(Number(e.target.value))} onPointerUp={commit} onKeyUp={commit} />
      <Value>{Math.round(v * 100) / 100}{unit}</Value>
    </label>
  )
}

// Speed on a doubling scale: the middle of the slider is 1×, each quarter
// of the way doubles or halves it.
function SpeedLine({ speed, onFix }: { speed: number; onFix: (x: number) => void }) {
  const [drag, setDrag] = useState<number | null>(null)
  const v = drag ?? Math.log2(speed)
  const shown = Math.round(2 ** v * 100) / 100
  const commit = () => { setDrag(null); if (Math.abs(shown - speed) > 1e-3) onFix(shown) }
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-3">
        <span className="w-24 shrink-0 font-serif text-[16px] text-zinc-100">Speed</span>
        <input type="range" min={-2} max={2} step={0.05} value={v} className="min-w-0 flex-1 accent-[#1f5f8b]"
               onChange={(e) => setDrag(Number(e.target.value))} onPointerUp={commit} onKeyUp={commit} />
        <Value>{shown}×</Value>
      </label>
      <div className="flex gap-1.5 pl-[6.75rem]">
        {[0.5, 1, 2, 4].map((x) => <Chip key={x} on={Math.abs(speed - x) < 1e-3} onClick={() => onFix(x)}>{x}×</Chip>)}
      </div>
    </div>
  )
}

function SoundLines({ gain, mute, fadeIn, fadeOut, onFix }: {
  gain: number; mute: boolean; fadeIn: number; fadeOut: number
  onFix: (patch: Patch, what: string) => void
}) {
  return (
    <div className="space-y-3">
      <Slider label="Volume" value={Math.round(gain * 100)} min={0} max={200} step={5} unit="%" disabled={mute}
              onCommit={(v) => onFix({ gain: v / 100 }, `set the volume to ${v}%`)} />
      <Slider label="Fade in" value={fadeIn} min={0} max={3} step={0.1} unit=" s"
              onCommit={(v) => onFix({ fade_in: v }, v ? `faded the sound in over ${v}s` : 'took the fade in off')} />
      <Slider label="Fade out" value={fadeOut} min={0} max={3} step={0.1} unit=" s"
              onCommit={(v) => onFix({ fade_out: v }, v ? `faded the sound out over ${v}s` : 'took the fade out off')} />
      <Line label="Mute">
        <Segmented options={[['off', 'Sound on'], ['on', 'Muted']]} value={mute ? 'on' : 'off'}
                   onPick={(x) => (x === 'on') !== mute && onFix({ mute: !mute }, mute ? 'unmuted the sound' : 'muted the sound')} />
      </Line>
    </div>
  )
}

/**
 * The shot as filmed, with the part the edit uses between two handles. Drag
 * a handle to start or end the shot elsewhere: shorter, or longer up to the
 * whole shot as filmed. One turn when let go.
 */
function TrimBar({ item, thumb, onTrim }: { item: SeqItem; thumb: string | null; onTrim: (edge: 'in' | 'out', to: number) => void }) {
  const box = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<{ edge: 'in' | 'out'; to: number } | null>(null)
  const lo = item.src_min ?? item.src_start
  const hi = Math.max(item.src_max ?? item.src_end, lo + 0.01)
  const a = drag?.edge === 'in' ? drag.to : item.src_start
  const b = drag?.edge === 'out' ? drag.to : item.src_end
  const pct = (t: number) => `${((t - lo) / (hi - lo)) * 100}%`
  const at = (clientX: number) => {
    const r = box.current!.getBoundingClientRect()
    return lo + Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * (hi - lo)
  }
  const handle = (edge: 'in' | 'out') => (
    <div role="slider" aria-label={edge === 'in' ? 'Where the shot starts' : 'Where the shot ends'} aria-valuenow={edge === 'in' ? a : b}
         className="absolute inset-y-0 z-10 flex w-4 -translate-x-1/2 cursor-ew-resize touch-none items-center justify-center rounded-md bg-accent"
         style={{ left: pct(edge === 'in' ? a : b) }}
         onPointerDown={(e) => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); setDrag({ edge, to: edge === 'in' ? a : b }) }}
         onPointerMove={(e) => {
           if (drag?.edge !== edge) return
           const t = at(e.clientX)
           setDrag({ edge, to: edge === 'in' ? Math.min(t, item.src_end - 0.2) : Math.max(t, item.src_start + 0.2) })
         }}
         onPointerUp={() => {
           const d = drag
           setDrag(null)
           if (d && Math.abs(d.to - (edge === 'in' ? item.src_start : item.src_end)) > 1 / 30) onTrim(edge, Math.round(d.to * 1000) / 1000)
         }}>
      <span className="h-4 w-0.5 rounded bg-white" />
    </div>
  )
  return (
    <div className="space-y-2">
      <div ref={box} className="relative h-12 rounded-lg bg-black"
           style={thumb ? { backgroundImage: `url(${thumb})`, backgroundSize: 'auto 100%', backgroundRepeat: 'repeat-x' } : undefined}>
        <span className="absolute inset-y-0 left-0 rounded-l-lg bg-white/65" style={{ width: pct(a) }} />
        <span className="absolute inset-y-0 right-0 rounded-r-lg bg-white/65" style={{ left: pct(b) }} />
        <span className="absolute inset-y-0 border-y-[3px] border-accent" style={{ left: pct(a), right: `calc(100% - ${pct(b)})` }} />
        {handle('in')}
        {handle('out')}
      </div>
      <div className="flex justify-between">
        <Value>{mmss(a)}</Value>
        <span className="self-center font-serif text-[15px] text-zinc-300">{((b - a) / (item.speed ?? 1)).toFixed(1)}s in the video</span>
        <Value>{mmss(b)}</Value>
      </div>
    </div>
  )
}

// "Save to My resources", where the thing was made (CapCut's "Save as preset").
// Always there; with nothing to keep yet it's quieter, and a click says what to do first.
export function SaveChip({ what, ready, onClick }: { what: string; ready: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} title={`Keep this ${what} in My resources, to use on any video`}
            className={cx('inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg border border-dashed px-3 py-1.5 font-serif text-[15px] hover:bg-raised',
              ready ? 'border-accent/60 text-accent' : 'border-line text-zinc-300')}>
      <Icon name="resources" size={17} /> Save {what} to My resources
    </button>
  )
}

export function Chip({ children, onClick, on, danger, disabled, title }: {
  children: ReactNode; onClick: () => void; on?: boolean; danger?: boolean; disabled?: boolean; title?: string
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={title}
            className={cx('inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg border px-3 py-1.5 font-serif text-[15px] disabled:opacity-40 disabled:pointer-events-none',
              on ? 'border-accent bg-accent text-accent-ink' : danger ? 'border-rose-200/40 text-rose-200 hover:bg-rose-500/10'
                : 'border-line bg-panel text-zinc-100 hover:bg-raised')}>
      {children}
    </button>
  )
}

// One line of a group, tuned on its own (sarah, 2026-10-20: "make them into a
// group of captions, and we can tune it independently"): the same controls
// as every caption's, for this line only, plus its size. Dragging the line on
// the picture moves it away from the rest of the group.
function LineLookPanel({ o, role, style, onLook }: {
  o: Overlay; role: LineRole; style: OverlayStyle; onLook: (look: LineLook | null, label: string) => void
}) {
  const L: LineLook = o.lines?.[role] ?? {}
  const name = lineName(o, role)
  const Name = name[0].toUpperCase() + name.slice(1)
  // what the sliders start from: this line's own settings over a plain line
  const own: OverlayStyle = { ...style, template: null, text_color: L.text_color ?? null, typeface: L.typeface ?? null,
    outline: L.outline ?? null, shadow: L.shadow ?? null, backdrop: L.backdrop ?? null, thick: L.thick ?? null }
  const say = (label: string) => label.replace(/^The captions/, Name).replace(/the captions'?/g, name)
  const scale = L.scale ?? 1
  return <>
    <Hint>Only {name} changes. The rest stays as it is and moves with it.</Hint>
    <Section title="Font">
      <CaptionFonts value={L.typeface ?? null} onPick={(f) => onLook({ typeface: f?.id ?? null }, f ? `${Name} is in ${f.name}` : `${Name} is back to its own font`)} />
    </Section>
    <Section title="Colour">
      <CaptionColours value={L.text_color ?? null} onPick={(c) => onLook({ text_color: c }, c ? `You changed the colour of ${name}` : `${Name} is back to its own colour`)} />
    </Section>
    <Slider label="Size" value={Math.round(scale * 100)} min={40} max={300} step={10} unit="%"
            onCommit={(v) => onLook({ scale: v === 100 ? null : v / 100 }, `You made ${name} ${v > scale * 100 ? 'bigger' : 'smaller'}`)} />
    <CaptionDress style={own} onPick={(patch, label) => onLook(patch as LineLook, say(label))} />
    <div className="flex flex-wrap gap-2">
      {!!(L.dx || L.dy) && <Chip onClick={() => onLook({ dx: null, dy: null }, `You put ${name} back in its place`)}>Put it back in its place</Chip>}
      {Object.keys(L).length > 0 && <Chip onClick={() => onLook(null, `${Name} is back to how it was`)}>Back to how it was</Chip>}
    </div>
  </>
}
