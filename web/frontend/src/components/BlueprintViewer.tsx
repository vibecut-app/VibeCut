/**
 * BlueprintViewer: Show EVERYTHING learned from the reference vlogs
 *
 * Instead of just showing a recipe, we show the complete blueprint:
 * - Fonts, sizes, colors, animations
 * - Transitions and their timing
 * - Effects used and intensity
 * - Color palette and grading
 * - Motion patterns
 * - Music analysis and beat sync
 * - Cut rhythm and timing
 * - Shot composition
 * - Text styling
 *
 * Organized as tabbed cards so the user can dig into any aspect.
 */

import { useState } from 'react'
import { cx } from '../ui'

export interface Blueprint {
  fonts: {
    fonts: Record<string, number>
    most_common: string | null
    colors: string[]
    animations: Record<string, number>
    entrance_duration_ms: number
    hold_duration_s: number
    positions: Record<string, number>
  }
  transitions: {
    transitions: Record<string, number>
    durations_ms: Record<string, number>
    on_beat_ratio: number
    usage_pattern: string
  }
  effects: {
    effects_used: Record<string, number>
    intensities: Record<string, number>
    duration_pattern: string
  }
  colors: {
    dominant_colors: string[]
    color_temperature: string
    saturation: string
    contrast_ratio: number
    lut_style: string
    brightness_level: string
    skin_tone_shift: string | null
  }
  motion: {
    camera_movements: Record<string, number>
    motion_intensity: string
    handheld_level: number
    stabilization_detected: boolean
  }
  music: {
    estimated_bpm: number
    music_energy: string
    drop_intensity: string
    instrumentation: string[]
    beat_sync_style: string
  }
  audio: {
    levels: Record<string, number>
    reverb_style: string | null
    noise_gate_enabled: boolean
  }
  cut_rhythm: {
    average_shot_duration_s: number
    longest_hold_s: number
    shortest_flash_ms: number
    cut_pattern: string
    beats_per_shot: number
  }
  composition: {
    aspect_ratios_used: string[]
    framing_rules: Record<string, number>
    shot_sizes: Record<string, number>
    subject_movement: string
  }
  text: {
    text_samples: string[]
    text_frequency: string
    average_text_duration_s: number
    emoji_usage: boolean
    lowercase_trend: boolean
  }
  style_one_liner: string
  key_techniques: string[]
  difficulty_level: string
}

type TabId = 'fonts' | 'transitions' | 'effects' | 'colors' | 'motion' | 'music' | 'audio' | 'rhythm' | 'composition' | 'text'

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: 'fonts', label: 'Fonts & Text', icon: '✏️' },
  { id: 'transitions', label: 'Transitions', icon: '✨' },
  { id: 'effects', label: 'Effects', icon: '🎬' },
  { id: 'colors', label: 'Color', icon: '🎨' },
  { id: 'motion', label: 'Motion', icon: '📹' },
  { id: 'music', label: 'Music', icon: '🎵' },
  { id: 'audio', label: 'Audio', icon: '🔊' },
  { id: 'rhythm', label: 'Cut Rhythm', icon: '⏱️' },
  { id: 'composition', label: 'Shots', icon: '🎞️' },
  { id: 'text', label: 'Text Overlays', icon: '💬' },
]

function TabContent({ blueprint, activeTab }: { blueprint: Blueprint; activeTab: TabId }) {
  const textAlign = 'text-[#1d1a17]'
  const labelColor = 'text-[#5d5650]'

  switch (activeTab) {
    case 'fonts':
      return (
        <div className="space-y-4">
          <div>
            <h4 className={`font-bold ${textAlign}`}>Fonts Used</h4>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(blueprint.fonts.fonts)
                .sort((a, b) => b[1] - a[1])
                .map(([font, count]) => (
                  <span
                    key={font}
                    className="rounded-full bg-[#f3efe8] px-3 py-1 text-sm font-semibold"
                  >
                    {font} <span className={`text-xs ${labelColor}`}>×{count}</span>
                  </span>
                ))}
            </div>
          </div>
          <div>
            <h4 className={`font-bold ${textAlign}`}>Caption Animations</h4>
            <div className="mt-2 space-y-1">
              {Object.entries(blueprint.fonts.animations)
                .sort((a, b) => b[1] - a[1])
                .map(([anim, count]) => (
                  <div key={anim} className="flex justify-between">
                    <span>{anim}</span>
                    <span className={labelColor}>×{count}</span>
                  </div>
                ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className={`text-xs ${labelColor}`}>Hold time</p>
              <p className="mt-1 text-xl font-bold">{blueprint.fonts.hold_duration_s.toFixed(1)}s</p>
            </div>
            <div>
              <p className={`text-xs ${labelColor}`}>Entrance</p>
              <p className="mt-1 text-xl font-bold">{blueprint.fonts.entrance_duration_ms}ms</p>
            </div>
          </div>
          <div>
            <p className={`text-xs ${labelColor}`}>Text Colors</p>
            <div className="mt-1.5 flex gap-2">
              {blueprint.fonts.colors.map((c) => (
                <div key={c} className="size-8 rounded-full border border-[#e2dcd2]" style={{ background: c }} />
              ))}
            </div>
          </div>
        </div>
      )

    case 'transitions':
      return (
        <div className="space-y-4">
          <div>
            <h4 className={`font-bold ${textAlign}`}>Transition Types</h4>
            <div className="mt-2 space-y-2">
              {Object.entries(blueprint.transitions.transitions)
                .sort((a, b) => b[1] - a[1])
                .map(([type, count]) => (
                  <div key={type} className="flex items-center justify-between">
                    <span>{type}</span>
                    <div className="flex items-center gap-2">
                      <div className="h-2 w-20 rounded-full bg-[#e2dcd2]">
                        <div className="h-2 rounded-full bg-accent" style={{ width: `${(count / 10) * 100}%` }} />
                      </div>
                      <span className={labelColor}>×{count}</span>
                    </div>
                  </div>
                ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className={`text-xs ${labelColor}`}>On-beat ratio</p>
              <p className="mt-1 text-xl font-bold">{Math.round(blueprint.transitions.on_beat_ratio * 100)}%</p>
            </div>
            <div>
              <p className={`text-xs ${labelColor}`}>Avg duration</p>
              <p className="mt-1 text-xl font-bold">
                {Math.round(
                  Object.values(blueprint.transitions.durations_ms).reduce((a, b) => a + b, 0) /
                    Object.values(blueprint.transitions.durations_ms).length
                )}
                ms
              </p>
            </div>
          </div>
          <p className={`rounded-lg bg-[#f3efe8] px-3 py-2 text-sm`}>
            <span className={labelColor}>Pattern:</span> {blueprint.transitions.usage_pattern}
          </p>
        </div>
      )

    case 'effects':
      return (
        <div className="space-y-4">
          <div>
            <h4 className={`font-bold ${textAlign}`}>Effects Used</h4>
            <div className="mt-2 space-y-2">
              {Object.entries(blueprint.effects.effects_used)
                .filter(([, count]) => count > 0)
                .sort((a, b) => b[1] - a[1])
                .map(([effect, count]) => (
                  <div key={effect} className="flex items-center justify-between">
                    <span>{effect}</span>
                    <div className="flex items-center gap-2">
                      <span className={labelColor}>
                        Intensity: {Math.round((blueprint.effects.intensities[effect] || 0.5) * 100)}%
                      </span>
                      <span className={labelColor}>×{count}</span>
                    </div>
                  </div>
                ))}
            </div>
            {Object.values(blueprint.effects.effects_used).every((c) => c === 0) && (
              <p className={labelColor}>No heavy effects</p>
            )}
          </div>
          <p className={`rounded-lg bg-[#f3efe8] px-3 py-2 text-sm`}>
            <span className={labelColor}>Duration pattern:</span> {blueprint.effects.duration_pattern}
          </p>
        </div>
      )

    case 'colors':
      return (
        <div className="space-y-4">
          <div>
            <h4 className={`font-bold ${textAlign}`}>Dominant Colors</h4>
            <div className="mt-2 flex gap-2">
              {blueprint.colors.dominant_colors.map((c) => (
                <div key={c} className="size-12 rounded-lg border-2 border-[#e2dcd2]" style={{ background: c }} title={c} />
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between">
              <p className={labelColor}>Color Temperature</p>
              <p className="font-semibold capitalize">{blueprint.colors.color_temperature}</p>
            </div>
            <div className="flex justify-between">
              <p className={labelColor}>Saturation</p>
              <p className="font-semibold capitalize">{blueprint.colors.saturation}</p>
            </div>
            <div className="flex justify-between">
              <p className={labelColor}>Contrast</p>
              <p className="font-semibold">{(blueprint.colors.contrast_ratio * 100).toFixed(0)}%</p>
            </div>
            <div className="flex justify-between">
              <p className={labelColor}>Brightness</p>
              <p className="font-semibold capitalize">{blueprint.colors.brightness_level}</p>
            </div>
          </div>
          <p className={`rounded-lg bg-[#f3efe8] px-3 py-2 text-sm`}>
            <span className={labelColor}>LUT style:</span> {blueprint.colors.lut_style}
          </p>
        </div>
      )

    case 'motion':
      return (
        <div className="space-y-4">
          <div>
            <h4 className={`font-bold ${textAlign}`}>Camera Movements</h4>
            <div className="mt-2 space-y-1">
              {Object.entries(blueprint.motion.camera_movements)
                .sort((a, b) => b[1] - a[1])
                .map(([move, count]) => (
                  <div key={move} className="flex justify-between">
                    <span>{move}</span>
                    <span className={labelColor}>×{count}</span>
                  </div>
                ))}
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between">
              <p className={labelColor}>Motion Intensity</p>
              <p className="font-semibold capitalize">{blueprint.motion.motion_intensity}</p>
            </div>
            <div className="flex justify-between">
              <p className={labelColor}>Handheld Level</p>
              <p className="font-semibold">{(blueprint.motion.handheld_level * 100).toFixed(0)}%</p>
            </div>
            <div className="flex justify-between">
              <p className={labelColor}>Stabilization</p>
              <p className="font-semibold">{blueprint.motion.stabilization_detected ? '✓ Yes' : 'No'}</p>
            </div>
          </div>
        </div>
      )

    case 'music':
      return (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className={`text-xs ${labelColor}`}>BPM</p>
              <p className="mt-1 text-2xl font-bold">{blueprint.music.estimated_bpm}</p>
            </div>
            <div>
              <p className={`text-xs ${labelColor}`}>Energy</p>
              <p className="mt-1 font-semibold capitalize">{blueprint.music.music_energy}</p>
            </div>
          </div>
          <div>
            <h4 className={`font-bold ${textAlign}`}>Instrumentation</h4>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {blueprint.music.instrumentation.map((instr) => (
                <span key={instr} className="rounded-full bg-[#f3efe8] px-3 py-1 text-sm capitalize">
                  {instr}
                </span>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between">
              <p className={labelColor}>Beat Sync</p>
              <p className="font-semibold capitalize">{blueprint.music.beat_sync_style}</p>
            </div>
            <div className="flex justify-between">
              <p className={labelColor}>Drop Intensity</p>
              <p className="font-semibold capitalize">{blueprint.music.drop_intensity}</p>
            </div>
          </div>
        </div>
      )

    case 'audio':
      return (
        <div className="space-y-4">
          <div>
            <h4 className={`font-bold ${textAlign}`}>Audio Levels (LUFS)</h4>
            <div className="mt-2 space-y-1">
              {Object.entries(blueprint.audio.levels).map(([track, level]) => (
                <div key={track} className="flex justify-between capitalize">
                  <span>{track}</span>
                  <span className={labelColor}>{level.toFixed(1)} dB</span>
                </div>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between">
              <p className={labelColor}>Reverb Style</p>
              <p className="font-semibold capitalize">{blueprint.audio.reverb_style || 'None'}</p>
            </div>
            <div className="flex justify-between">
              <p className={labelColor}>Noise Gate</p>
              <p className="font-semibold">{blueprint.audio.noise_gate_enabled ? '✓ On' : 'Off'}</p>
            </div>
          </div>
        </div>
      )

    case 'rhythm':
      return (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className={`text-xs ${labelColor}`}>Avg Shot Length</p>
              <p className="mt-1 text-2xl font-bold">{blueprint.cut_rhythm.average_shot_duration_s.toFixed(1)}s</p>
            </div>
            <div>
              <p className={`text-xs ${labelColor}`}>Beats/Shot</p>
              <p className="mt-1 text-2xl font-bold">{blueprint.cut_rhythm.beats_per_shot.toFixed(1)}</p>
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between">
              <p className={labelColor}>Shortest Flash</p>
              <p className="font-semibold">{blueprint.cut_rhythm.shortest_flash_ms}ms</p>
            </div>
            <div className="flex justify-between">
              <p className={labelColor}>Longest Hold</p>
              <p className="font-semibold">{blueprint.cut_rhythm.longest_hold_s.toFixed(1)}s</p>
            </div>
          </div>
          <p className={`rounded-lg bg-[#f3efe8] px-3 py-2 text-sm`}>
            <span className={labelColor}>Pattern:</span> {blueprint.cut_rhythm.cut_pattern}
          </p>
        </div>
      )

    case 'composition':
      return (
        <div className="space-y-4">
          <div>
            <h4 className={`font-bold ${textAlign}`}>Aspect Ratios</h4>
            <div className="mt-2 flex flex-wrap gap-2">
              {blueprint.composition.aspect_ratios_used.map((ar) => (
                <span key={ar} className="rounded-lg bg-[#f3efe8] px-3 py-1 text-sm font-semibold">
                  {ar}
                </span>
              ))}
            </div>
          </div>
          <div>
            <h4 className={`font-bold ${textAlign}`}>Shot Sizes</h4>
            <div className="mt-2 space-y-1">
              {Object.entries(blueprint.composition.shot_sizes).map(([size, count]) => (
                <div key={size} className="flex justify-between capitalize">
                  <span>{size}</span>
                  <span className={labelColor}>×{count}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between">
              <p className={labelColor}>Framing Rule</p>
              <p className="font-semibold">
                {Object.entries(blueprint.composition.framing_rules)
                  .sort((a, b) => b[1] - a[1])[0]?.[0] || 'Varied'}
              </p>
            </div>
            <div className="flex justify-between">
              <p className={labelColor}>Subject Movement</p>
              <p className="font-semibold capitalize">{blueprint.composition.subject_movement}</p>
            </div>
          </div>
        </div>
      )

    case 'text':
      return (
        <div className="space-y-4">
          <div>
            <h4 className={`font-bold ${textAlign}`}>Text Samples</h4>
            <div className="mt-2 space-y-1 text-sm">
              {blueprint.text.text_samples.slice(0, 5).map((text, i) => (
                <p key={i} className={labelColor}>
                  "{text}"
                </p>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between">
              <p className={labelColor}>Text Frequency</p>
              <p className="font-semibold capitalize">{blueprint.text.text_frequency}</p>
            </div>
            <div className="flex justify-between">
              <p className={labelColor}>Avg Duration</p>
              <p className="font-semibold">{blueprint.text.average_text_duration_s.toFixed(1)}s</p>
            </div>
            <div className="flex justify-between">
              <p className={labelColor}>Emoji Used</p>
              <p className="font-semibold">{blueprint.text.emoji_usage ? '✓ Yes' : 'No'}</p>
            </div>
            <div className="flex justify-between">
              <p className={labelColor}>Lowercase Trend</p>
              <p className="font-semibold">{blueprint.text.lowercase_trend ? '✓ Yes' : 'No'}</p>
            </div>
          </div>
        </div>
      )
  }
}

export function BlueprintViewer({ blueprint, onClose }: { blueprint: Blueprint; onClose: () => void }) {
  const [activeTab, setActiveTab] = useState<TabId>('fonts')

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="rounded-[22px] border border-[#ece6dc] bg-white p-6">
        <h2 className="text-2xl font-bold text-[#1d1a17]">{blueprint.style_one_liner}</h2>
        <p className="mt-2 text-[#5d5650]">
          <strong>Difficulty:</strong> {blueprint.difficulty_level}
        </p>
        <div className="mt-4">
          <p className="text-sm font-semibold text-[#5d5650]">KEY TECHNIQUES</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {blueprint.key_techniques.map((tech) => (
              <span key={tech} className="rounded-full bg-[#ffe0e8] px-3 py-1 text-sm font-semibold text-[#1d1a17]">
                {tech}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="flex overflow-x-auto gap-2 border-b border-[#e2dcd2]">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cx(
              'shrink-0 border-b-2 px-4 py-3 font-semibold transition-colors',
              activeTab === tab.id
                ? 'border-accent text-[#1d1a17]'
                : 'border-transparent text-[#5d5650] hover:text-[#1d1a17]'
            )}
          >
            <span className="mr-1">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="rounded-[22px] border border-[#ece6dc] bg-white p-6">
        <TabContent blueprint={blueprint} activeTab={activeTab} />
      </div>

      {/* Action */}
      <button
        onClick={onClose}
        className="w-full rounded-full bg-[#1d1a17] py-4 text-lg font-bold text-white shadow-[0_6px_20px_-6px_rgba(29,26,23,0.5)] transition-all hover:-translate-y-px hover:bg-[#2c2824]"
      >
        Got it, let's apply this →
      </button>
    </div>
  )
}
