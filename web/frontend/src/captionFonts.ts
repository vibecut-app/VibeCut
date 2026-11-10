// The caption fonts people reach for in CapCut, TikTok and Reels edits
// (sarah, 2026-10-18: "i want the popular ones to all be in our app").
// The apps' own faces are proprietary, so these are the openly licensed
// faces those edits use or that read the same way, shipped with the app in
// public/fonts (OFL 1.1 / Apache 2.0, licence beside each) so preview and
// export draw identical letters with no network. Their families carry a
// "VC " prefix so a Mac's own copy, or the looks' older names, never stand in.
// `size` evens out how big each face reads at the same pixel size.
export type CaptionFont = { id: string; name: string; family: string; weight: number; size: number }

const F = (id: string, name: string, weight: number, size = 1, fallback = 'sans-serif', family = name): CaptionFont =>
  ({ id, name, family: `"VC ${family}", ${fallback}`, weight, size })

// Quiet first (sarah, 2026-11-10: "the fonts we use right now are not the
// ones the good vlogs would use"). The good day vlogs in the taste set write
// small, light and mostly lowercase (a caption about 4% of the frame tall, a
// quarter of its words in capitals); which faces they use wasn't measured,
// so these are the open faces that read like them: a thin sans, a light
// geometric sans, a soft italic serif, a rounded sans, a thin hand.
export const CAPTION_FONTS: CaptionFont[] = [
  F('inter-light', 'Inter Light', 300, 1, 'sans-serif', 'Inter'),
  F('montserrat-light', 'Montserrat Light', 300, 0.95, 'sans-serif', 'Montserrat'),
  F('poppins-light', 'Poppins Light', 300, 0.95, 'sans-serif', 'Poppins'),
  F('cormorant-italic', 'Cormorant Italic', 500, 1.2, 'serif', 'Cormorant Garamond Italic'),
  F('nunito', 'Nunito', 500, 1),
  F('reenie-beanie', 'Reenie Beanie', 400, 1.45, 'cursive'),
  F('caveat', 'Caveat', 700, 1.3, 'cursive'),
  F('courier-prime', 'Courier Prime', 400, 1, 'monospace'),
  F('playfair-display', 'Playfair Display', 700, 1, 'serif'),
  F('tiktok-sans', 'TikTok Sans', 800),
  F('montserrat', 'Montserrat', 800, 0.95),
  F('poppins', 'Poppins', 700, 0.95),
  F('bebas-neue', 'Bebas Neue', 400, 1.25),
  F('anton', 'Anton', 400, 1.1),
  F('fredoka', 'Fredoka', 600, 1.02),
  F('pacifico', 'Pacifico', 400, 0.95, 'cursive'),
]

// Taken out of the picker for the quiet ones; a video that already uses one
// keeps drawing it (the files stay, and the 3D word art letters with Luckiest Guy).
const RETIRED: CaptionFont[] = [
  F('archivo-black', 'Archivo Black', 400, 0.92),
  F('luckiest-guy', 'Luckiest Guy', 400, 1, 'cursive'),
  F('bangers', 'Bangers', 400, 1.15, 'cursive'),
  F('permanent-marker', 'Permanent Marker', 400, 1, 'cursive'),
  F('lobster', 'Lobster', 400, 1.08, 'cursive'),
]

export const fontById = (id: string | null | undefined): CaptionFont | null =>
  (id && [...CAPTION_FONTS, ...RETIRED].find((f) => f.id === id)) || null
