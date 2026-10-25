/**
 * LearnVibe: Show what was learned from YouTube references with visual examples
 * and adjustable sliders.
 *
 * User flow:
 * 1. Paste YouTube links
 * 2. App analyzes them and shows a recipe carousel
 * 3. Each card in the carousel shows what was learned (animations, transitions, effects, etc.)
 * 4. User can adjust sliders for how much of each to apply
 * 5. Before/after preview shows effect on a sample clip
 * 6. Apply to video
 */

import { useState } from 'react'
import { cx } from '../ui'

export interface Recipe {
  captions: {
    animations: Record<string, number>
    avg_hold_s: number
    frequency: string
    position_band: string
  }
  transitions: {
    kinds: Record<string, number>
    frequency: string
    avg_duration_s: number
    on_beat_ratio: number
  }
  effects: {
    effects: Record<string, number>
    frequency: string
    avg_intensity: number
  }
  pacing: {
    avg_shot_length_s: number
    hook_length_s: number
    tempo_bpm: number
    energy_arc: string
  }
  look: {
    warmth: string
    saturation: string
    contrast: string
    brightness: string
  }
  summary_line: string
}

interface RecipeCardProps {
  recipe: Recipe
  onAdjust: (key: string, value: number) => void
  adjustments: Record<string, number>
}

function RecipeCard({ recipe, onAdjust, adjustments }: RecipeCardProps) {
  const cards = [
    {
      id: 'captions',
      title: 'Caption Style',
      icon: '💬',
      content: (
        <div className="space-y-3">
          <div>
            <p className="text-sm font-semibold text-[#1d1a17]">Animations</p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {Object.entries(recipe.captions.animations)
                .filter(([, count]) => count > 0)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 3)
                .map(([name, count]) => (
                  <span
                    key={name}
                    className="inline-block rounded-full bg-[#ffe0e8] px-2.5 py-1 text-xs font-bold text-[#1d1a17]"
                  >
                    {name} ×{count}
                  </span>
                ))}
            </div>
          </div>
          <div>
            <p className="text-xs text-[#5d5650]">Hold time: {recipe.captions.avg_hold_s.toFixed(1)}s</p>
            <p className="text-xs text-[#5d5650]">Position: {recipe.captions.position_band}</p>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <label className="text-sm font-semibold">Apply intensity:</label>
            <input
              type="range"
              min="0"
              max="100"
              value={adjustments.captions ?? 100}
              onChange={(e) => onAdjust('captions', parseInt(e.target.value))}
              className="w-24"
            />
          </div>
        </div>
      ),
    },
    {
      id: 'transitions',
      title: 'Transitions',
      icon: '✨',
      content: (
        <div className="space-y-3">
          <div>
            <p className="text-sm font-semibold text-[#1d1a17]">Types used</p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {Object.entries(recipe.transitions.kinds)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 4)
                .map(([kind, count]) => (
                  <span
                    key={kind}
                    className="inline-block rounded-full bg-[#dcecfb] px-2.5 py-1 text-xs font-bold text-[#1f5f8b]"
                  >
                    {kind} ×{count}
                  </span>
                ))}
            </div>
          </div>
          <div>
            <p className="text-xs text-[#5d5650]">Frequency: {recipe.transitions.frequency}</p>
            <p className="text-xs text-[#5d5650]">On-beat: {Math.round(recipe.transitions.on_beat_ratio * 100)}%</p>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <label className="text-sm font-semibold">Apply intensity:</label>
            <input
              type="range"
              min="0"
              max="100"
              value={adjustments.transitions ?? 100}
              onChange={(e) => onAdjust('transitions', parseInt(e.target.value))}
              className="w-24"
            />
          </div>
        </div>
      ),
    },
    {
      id: 'effects',
      title: 'Visual Effects',
      icon: '🎬',
      content: (
        <div className="space-y-3">
          <div>
            <p className="text-sm font-semibold text-[#1d1a17]">Effects used</p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {Object.entries(recipe.effects.effects)
                .filter(([, count]) => count > 0)
                .map(([name]) => (
                  <span
                    key={name}
                    className="inline-block rounded-full bg-[#fff3c4] px-2.5 py-1 text-xs font-bold text-[#1d1a17]"
                  >
                    {name}
                  </span>
                ))}
            </div>
            {Object.values(recipe.effects.effects).every((c) => c === 0) && (
              <p className="text-xs text-[#5d5650]">No heavy effects detected</p>
            )}
          </div>
          <div>
            <p className="text-xs text-[#5d5650]">Intensity: {recipe.effects.frequency}</p>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <label className="text-sm font-semibold">Apply intensity:</label>
            <input
              type="range"
              min="0"
              max="100"
              value={adjustments.effects ?? 100}
              onChange={(e) => onAdjust('effects', parseInt(e.target.value))}
              className="w-24"
            />
          </div>
        </div>
      ),
    },
    {
      id: 'pacing',
      title: 'Pacing & Rhythm',
      icon: '🎵',
      content: (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <p className="text-xs text-[#5d5650]">Avg shot length</p>
              <p className="mt-0.5 text-lg font-bold text-[#1d1a17]">{recipe.pacing.avg_shot_length_s.toFixed(1)}s</p>
            </div>
            <div>
              <p className="text-xs text-[#5d5650]">Tempo</p>
              <p className="mt-0.5 text-lg font-bold text-[#1d1a17]">{recipe.pacing.tempo_bpm} BPM</p>
            </div>
          </div>
          <div>
            <p className="text-xs text-[#5d5650]">Energy: {recipe.pacing.energy_arc}</p>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <label className="text-sm font-semibold">Apply intensity:</label>
            <input
              type="range"
              min="0"
              max="100"
              value={adjustments.pacing ?? 100}
              onChange={(e) => onAdjust('pacing', parseInt(e.target.value))}
              className="w-24"
            />
          </div>
        </div>
      ),
    },
    {
      id: 'look',
      title: 'Color & Grade',
      icon: '🎨',
      content: (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <p className="text-xs text-[#5d5650]">Warmth</p>
              <p className="mt-0.5 font-bold text-[#1d1a17] capitalize">{recipe.look.warmth}</p>
            </div>
            <div>
              <p className="text-xs text-[#5d5650]">Saturation</p>
              <p className="mt-0.5 font-bold text-[#1d1a17] capitalize">{recipe.look.saturation}</p>
            </div>
            <div>
              <p className="text-xs text-[#5d5650]">Contrast</p>
              <p className="mt-0.5 font-bold text-[#1d1a17] capitalize">{recipe.look.contrast}</p>
            </div>
            <div>
              <p className="text-xs text-[#5d5650]">Brightness</p>
              <p className="mt-0.5 font-bold text-[#1d1a17] capitalize">{recipe.look.brightness}</p>
            </div>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <label className="text-sm font-semibold">Apply intensity:</label>
            <input
              type="range"
              min="0"
              max="100"
              value={adjustments.look ?? 100}
              onChange={(e) => onAdjust('look', parseInt(e.target.value))}
              className="w-24"
            />
          </div>
        </div>
      ),
    },
  ]

  const [activeCard, setActiveCard] = useState(0)

  const card = cards[activeCard]

  return (
    <div className="space-y-4">
      {/* Carousel navigation */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setActiveCard((c) => (c - 1 + cards.length) % cards.length)}
          className="grid size-10 place-items-center rounded-full border border-[#e2dcd2] bg-white text-lg font-bold shadow-sm hover:border-[#cfc7bb]"
        >
          ←
        </button>
        <div className="flex-1 overflow-hidden">
          <div className="flex gap-2">
            {cards.map((c, i) => (
              <button
                key={c.id}
                onClick={() => setActiveCard(i)}
                className={cx(
                  'shrink-0 rounded-full px-3 py-1 text-sm font-semibold transition-all',
                  i === activeCard
                    ? 'bg-[#1d1a17] text-white'
                    : 'bg-white text-[#5d5650] shadow-sm hover:text-[#1d1a17]'
                )}
              >
                {c.icon}
              </button>
            ))}
          </div>
        </div>
        <button
          onClick={() => setActiveCard((c) => (c + 1) % cards.length)}
          className="grid size-10 place-items-center rounded-full border border-[#e2dcd2] bg-white text-lg font-bold shadow-sm hover:border-[#cfc7bb]"
        >
          →
        </button>
      </div>

      {/* Card content */}
      <div className="rounded-[22px] border border-[#ece6dc] bg-white p-6">
        <h3 className="text-xl font-bold text-[#1d1a17]">{card.title}</h3>
        <p className="mt-0.5 text-sm text-[#5d5650]">{card.icon}</p>
        <div className="mt-4">{card.content}</div>
      </div>
    </div>
  )
}

interface BeforeAfterProps {
  adjustment: number
}

function BeforeAfter({ adjustment }: BeforeAfterProps) {
  const [side, setSide] = useState<'before' | 'after'>('before')

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <button
          onClick={() => setSide('before')}
          className={cx(
            'flex-1 rounded-full px-4 py-2 text-sm font-semibold transition-all',
            side === 'before'
              ? 'bg-[#1d1a17] text-white'
              : 'bg-white text-[#5d5650] shadow-sm hover:text-[#1d1a17]'
          )}
        >
          Before
        </button>
        <button
          onClick={() => setSide('after')}
          className={cx(
            'flex-1 rounded-full px-4 py-2 text-sm font-semibold transition-all',
            side === 'after'
              ? 'bg-[#1d1a17] text-white'
              : 'bg-white text-[#5d5650] shadow-sm hover:text-[#1d1a17]'
          )}
        >
          After ({adjustment}%)
        </button>
      </div>

      {/* Mock preview */}
      <div className="aspect-video overflow-hidden rounded-xl border border-[#e2dcd2] bg-black">
        <div className="grid h-full place-items-center text-white">
          <div className="text-center">
            <div className="text-6xl opacity-20">▶</div>
            <p className="mt-2 text-sm text-white/60">
              {side === 'before' ? 'Your original clip' : 'With recipe applied'}
            </p>
            {side === 'after' && (
              <p className="mt-1 text-xs text-white/40">
                Intensity: {adjustment}% (slide to adjust)
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export function LearnVibePreview({ recipe, onApply }: { recipe: Recipe; onApply: () => void }) {
  const [adjustments, setAdjustments] = useState<Record<string, number>>({
    captions: 100,
    transitions: 100,
    effects: 100,
    pacing: 100,
    look: 100,
  })

  const handleAdjust = (key: string, value: number) => {
    setAdjustments((prev) => ({ ...prev, [key]: value }))
  }

  // Average adjustment for the preview
  const avgAdjustment = Math.round(
    Object.values(adjustments).reduce((a, b) => a + b, 0) / Object.values(adjustments).length
  )

  return (
    <div className="space-y-8 rounded-[28px] border border-[#ece6dc] bg-white p-8">
      <div>
        <h2 className="text-2xl font-bold text-[#1d1a17]">Your recipe</h2>
        <p className="mt-1 text-[#5d5650]">{recipe.summary_line}</p>
      </div>

      <div className="grid gap-8 lg:grid-cols-2">
        {/* Recipe carousel with sliders */}
        <RecipeCard recipe={recipe} onAdjust={handleAdjust} adjustments={adjustments} />

        {/* Before/after preview */}
        <BeforeAfter adjustment={avgAdjustment} />
      </div>

      {/* Apply button */}
      <button
        onClick={onApply}
        className="w-full rounded-full bg-[#1d1a17] py-4 text-lg font-bold text-white shadow-[0_6px_20px_-6px_rgba(29,26,23,0.5)] transition-all hover:-translate-y-px hover:bg-[#2c2824]"
      >
        Apply this recipe to my video → ({Math.round(avgAdjustment)}% intensity)
      </button>
    </div>
  )
}
