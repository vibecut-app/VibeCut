// Line icons for the edit screen's rail, tabs and toolbars: one stroke
// weight, drawn on a 24 grid, coloured by the text around them.

const PATHS = {
  media: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  text: 'M5 6V5h14v1M12 5v14M9 19h6',
  music: 'M9 18V6l11-2v12M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM20 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z',
  spark: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z',
  history: 'M3 12a9 9 0 1 0 3-6.7M3 4v4h4M12 7v5l3 2',
  scissors: 'M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.1 7.9L20 20M8.1 16.1L20 4',
  cc: 'M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM10.5 10a2.5 2.5 0 1 0 0 4M17.5 10a2.5 2.5 0 1 0 0 4',
  adjust: 'M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M16 4v4M10 10v4M18 16v4',
  undo: 'M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-4',
  redo: 'M15 14l5-5-5-5M20 9H9a5 5 0 0 0 0 10h4',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  export: 'M12 15V3M7 8l5-5 5 5M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5',
  split: 'M12 3v18M8 7l-4 5 4 5M16 7l4 5-4 5',
  trash: 'M4 7h16M10 11v6M14 11v6M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12M9 7V4h6v3',
  full: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5',
  minus: 'M5 12h14',
  plus: 'M12 5v14M5 12h14',
  frame: 'M8 3h8a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z',
  wide: 'M3 7h18a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z',
  video: 'M3 7a1 1 0 0 1 1-1h11a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1zM16 10l5-3v10l-5-3',
  lines: 'M4 5h16v14H4zM8 10h8M8 14h5',
  turnL: 'M4 4v5h5M4.5 9A8 8 0 1 1 6 17',
  turnR: 'M20 4v5h-5M19.5 9A8 8 0 1 0 18 17',
  copy: 'M9 9h10v10H9zM5 15V5h10',
  paste: 'M9 4h6v3H9zM7 5.5H5V21h14V5.5h-2M9 13h6M9 17h4',
  freeze: 'M12 2v20M4.5 6.5l15 11M19.5 6.5l-15 11M9.5 3.5 12 6l2.5-2.5M9.5 20.5 12 18l2.5 2.5',
  reverse: 'M9 5 4 10l5 5M4 10h11a5 5 0 0 1 0 10h-3',
  // My resources: a folder with a heart in it (Media is the plain folder)
  resources: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM12 16.2l-2.5-2.4a1.55 1.55 0 0 1 2.5-1.8 1.55 1.55 0 0 1 2.5 1.8z',
  pencil: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0',
  // Graphic animations: a square, a circle, a triangle and a star
  shapes: 'M4 4h6.5v6.5H4zM17.25 4a3.25 3.25 0 1 1 0 6.5 3.25 3.25 0 0 1 0-6.5zM7.25 13.5l3.75 6.5h-7.5zM17.25 13.2l1.15 2.45 2.65.3-2 1.8.6 2.65-2.4-1.4-2.4 1.4.6-2.65-2-1.8 2.65-.3z',
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 20, className }: { name: IconName | 'play' | 'pause'; size?: number; className?: string }) {
  if (name === 'play' || name === 'pause') {
    return (
      <svg viewBox="0 0 24 24" width={size} height={size} className={className} aria-hidden fill="currentColor">
        {name === 'play' ? <path d="M7 4.5v15a1 1 0 0 0 1.5.9l12-7.5a1 1 0 0 0 0-1.7l-12-7.5A1 1 0 0 0 7 4.5z" />
          : <path d="M6 4h4v16H6zM14 4h4v16h-4z" />}
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} aria-hidden
         fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[name]} />
    </svg>
  )
}
