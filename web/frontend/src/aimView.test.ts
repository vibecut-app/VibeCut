// A filled shot's crop in the preview is the crop the export cuts.
//
// A vertical clip in a wide frame (the case of 2026-10-26): the point Make
// aimed at, off to one side, puts the window on that side -- the same
// window export._fit's crop expression cuts; a point in the middle keeps
// the middle (control); a point near the edge stops at the edge; the point
// sits HEAD_AT down; no aim leaves CSS's own centre.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { aimPosition, HEAD_AT } from './aimView.ts'

// The crop's top-left corner as export._fit computes it (ffmpeg: clip(x, lo, hi)).
function exportCrop(aim: [number, number], W: number, H: number, vw: number, vh: number) {
  const k = Math.max(W / vw, H / vh)
  const iw = vw * k, ih = vh * k
  const clip = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
  return { x: clip(aim[0] * iw - W / 2, 0, iw - W), y: clip(aim[1] * ih - H * HEAD_AT, 0, ih - H), iw, ih }
}
// The same corner from a CSS object-position (object-fit: cover): offset = (image - box) * share.
function cssCrop(pos: string, W: number, H: number, vw: number, vh: number) {
  const [px, py] = pos.split(' ').map((v) => parseFloat(v) / 100)
  const k = Math.max(W / vw, H / vh)
  return { x: (vw * k - W) * px, y: (vh * k - H) * py }
}

// a wide 16:9 player box and a vertical 1080 × 1920 picture
const W = 960, H = 540, vw = 1080, vh = 1920

test('a face off to one side: the preview crops where the export crops', () => {
  for (const aim of [[0.2, 0.3], [0.75, 0.25], [0.5, 0.6]] as [number, number][]) {
    const pos = aimPosition(aim, W, H, vw, vh)
    const a = exportCrop(aim, W, H, vw, vh), b = cssCrop(pos, W, H, vw, vh)
    assert.ok(Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5, `${aim}: export (${a.x}, ${a.y}) vs preview (${b.x}, ${b.y})`)
  }
})

test('the window moves toward the face: lower on the picture for a face low down, the middle for a face in the middle', () => {
  const high = cssCrop(aimPosition([0.5, 0.2], W, H, vw, vh), W, H, vw, vh)
  const low = cssCrop(aimPosition([0.5, 0.7], W, H, vw, vh), W, H, vw, vh)
  assert.ok(low.y > high.y + 100, `${high.y} → ${low.y}`)
  // a vertical picture covering a wide box is cropped top and bottom only: across it stays centred
  assert.equal(aimPosition([0.5, 0.5], W, H, vw, vh).split(' ')[0], '50.00%')
})

test('the face sits HEAD_AT down the crop when there is room', () => {
  const aim: [number, number] = [0.5, 0.5]
  const k = Math.max(W / vw, H / vh)
  const b = cssCrop(aimPosition(aim, W, H, vw, vh), W, H, vw, vh)
  const faceInCrop = (aim[1] * vh * k - b.y) / H
  assert.ok(Math.abs(faceInCrop - HEAD_AT) < 0.01, String(faceInCrop))
})

test('near the edge it stops at the edge, and no aim keeps CSS centring', () => {
  assert.equal(aimPosition([0.5, 0.01], W, H, vw, vh).split(' ')[1], '0.00%')
  assert.equal(aimPosition([0.5, 0.99], W, H, vw, vh).split(' ')[1], '100.00%')
  assert.equal(aimPosition(null, W, H, vw, vh), '')
  assert.equal(aimPosition([0.3, 0.3], 0, 0, vw, vh), '')
})
