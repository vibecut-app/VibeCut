// A filled shot's crop in the preview, cut where the export cuts it.
//
// Make fills a shot filmed the other way to the frame (a vertical clip in a
// wide video) and aims the crop at the people in it (backend aim.py, board
// `aim`). export._fit crops ffmpeg's way: the window centred across on the
// point, the point HEAD_AT down, stopped at the picture's edge. The player
// fills with CSS object-fit: cover, which keeps the middle unless told
// otherwise; this is the object-position that puts the same window on screen.

export const HEAD_AT = 0.4   // aim.HEAD_AT: a face's centre this far down the crop

/** Where a filled, unturned shot's crop sits, as export._fit cuts it: centred
 *  across on the aim point and with it HEAD_AT down, stopping at the picture's
 *  edge -- as a CSS object-position, so the preview shows the export's crop. */
export function aimPosition(aim: [number, number] | null | undefined, W: number, H: number, vw: number, vh: number): string {
  if (!aim || !(W > 0 && H > 0 && vw > 0 && vh > 0)) return ''
  const k = Math.max(W / vw, H / vh)
  const iw = vw * k, ih = vh * k
  const share = (want: number, room: number) => room > 0.5 ? Math.min(1, Math.max(0, want / room)) : 0.5
  const x = share(aim[0] * iw - W / 2, iw - W)
  const y = share(aim[1] * ih - H * HEAD_AT, ih - H)
  return `${(x * 100).toFixed(2)}% ${(y * 100).toFixed(2)}%`
}

/** The blur behind a whole picture (board backdrop "blur", set by Make where
 *  filling the frame would cut a face off): the shot itself, covering the
 *  frame, drawn small, blurred and darkened -- export._fit's BACKDROP_*,
 *  so the preview shows what the export renders. */
export const BACKDROP = { scale: 8, sigma: 10, dim: 0.8 }

export function drawBackdrop(canvas: HTMLCanvasElement, video: HTMLVideoElement): boolean {
  const W = canvas.clientWidth, H = canvas.clientHeight, vw = video.videoWidth, vh = video.videoHeight
  if (!(W > 0 && H > 0 && vw > 0 && vh > 0)) return false
  const cw = Math.max(2, Math.round(W / BACKDROP.scale)), ch = Math.max(2, Math.round(H / BACKDROP.scale))
  if (canvas.width !== cw) canvas.width = cw
  if (canvas.height !== ch) canvas.height = ch
  const ctx = canvas.getContext('2d')
  if (!ctx) return false
  const k = Math.max(cw / vw, ch / vh)
  const dw = vw * k, dh = vh * k
  // drawn a blur's width past every edge, so the edges don't fade to black (ffmpeg's gblur keeps them)
  const o = BACKDROP.sigma * 2
  ctx.filter = `blur(${BACKDROP.sigma}px) brightness(${BACKDROP.dim})`
  ctx.drawImage(video, (cw - dw) / 2 - o, (ch - dh) / 2 - o, dw + 2 * o, dh + 2 * o)
  return true
}
