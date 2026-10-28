// SY OS stickers, drawn with fun-isometric (kit copied beside this file).
import { VIEWS, ellipse, onFace, poly, rect, spark } from './fun'
import { glint, hop, tossLag, wiggle } from './motions'
import type { Icon, Layer, Motion, Vec } from './fun'

const LINE = 5
const { tilt: FACE, extrude: EXT } = VIEWS.right

const glow = (parent: string, p: Vec, r: number, m: Motion, extra: { ip?: number; op?: number } = {}): Layer => ({
  parent,
  a: p,
  p,
  m,
  ...extra,
  shapes: [{ d: spark(p[0], p[1], r), fill: 'white' }],
})

// a folded tee seen from above: body, sleeves turned in along the sides, a ribbed neck
const SLEEVE_L = poly([[-120, -92], [-62, -92], [-120, -8]], 8)
const SLEEVE_R = poly([[120, -92], [62, -92], [120, -8]], 8)
const tee = (body: 'main' | 'tint', rib: 'deep' | 'main') => [
  { d: rect(-120, -92, 240, 184, 18), fill: body, depth: 0.55 },
  { d: SLEEVE_L, fill: body, depth: 0.2 },
  { d: SLEEVE_R, fill: body, depth: 0.2 },
  { d: ellipse(0, -70, 46, 24), fill: rib, depth: 0.25 },
  { d: ellipse(0, -72, 30, 13), fill: 'tint' as const },
  { d: 'M-70 48L70 44', line: 4 }, // the fold
]

export const foldedTee: Icon = {
  name: 'foldedTee',
  frames: 150,
  line: LINE,
  extrude: EXT,
  still: 0,
  layers: [
    // the shirt underneath stays put; the top one hops off it and lands
    { p: [238, 292], tilt: FACE, shapes: tee('tint', 'main') },
    { id: 'top', p: [226, 240], m: hop, shapes: [] },
    { id: 'face', parent: 'top', tilt: FACE, shapes: [...tee('main', 'deep'), { d: rect(-24, -24, 48, 26, 5), fill: 'white', depth: 0.15 }] },
    {
      parent: 'face',
      a: [104, 78],
      p: [104, 78],
      m: [{ ...tossLag, at: 5, k: 1.3 }],
      shapes: [
        { d: 'M104 78L132 118', line: 4 },
        { d: poly([[108, 114], [170, 108], [176, 186], [114, 192]], 8), fill: 'gold', depth: 0.35 },
        { d: ellipse(130, 128, 7, 7), fill: 'ink', line: false },
        { d: 'M128 152L160 149M130 168L152 166', line: 4 },
      ],
    },
    glow('top', [-150, -110], 26, glint(50, 104)),
    glow('top', [152, -126], 22, glint(54, 96)),
    glow('top', [-40, -170], 18, glint(58, 90)),
  ],
}

// ---------- knitting: a yarn cone feeding a swatch on two needles ----------

// rows of jersey stitches, each a small V
const STITCHES = Array.from({ length: 4 }, (_, r) =>
  Array.from({ length: 6 }, (_, c) => {
    const [x, y] = [-60 + c * 24, -30 + r * 24]
    return `M${x - 10} ${y - 8}L${x} ${y + 8}L${x + 10} ${y - 8}`
  }).join(''),
).join('')

// a needle as a thin slab from a to b, knob at a
const needle = ([ax, ay]: Vec, [bx, by]: Vec, w = 7) => {
  const [dx, dy] = [bx - ax, by - ay]
  const len = Math.hypot(dx, dy)
  const [nx, ny] = [(-dy / len) * w, (dx / len) * w]
  return poly([[ax + nx, ay + ny], [bx + nx * 0.2, by + ny * 0.2], [bx - nx * 0.2, by - ny * 0.2], [ax - nx, ay - ny]], 2)
}
const PIVOT: Vec = [0, -72]
const CONE_AT: Vec = [132, 304]
const KNIT_AT: Vec = [336, 286]
// the yarn: from the cone's tube to where the needles cross, both points projected through the same lean as the faces
const add = ([a, b]: Vec, [c, d]: Vec): Vec => [a + c, b + d]
const [TIP, CROSS] = [add(CONE_AT, onFace(FACE, [0, -124])), add(KNIT_AT, onFace(FACE, PIVOT))]
const YARN = `M${TIP[0].toFixed(1)} ${TIP[1].toFixed(1)}C${(TIP[0] + 40).toFixed(1)} ${(TIP[1] - 70).toFixed(1)} ${(CROSS[0] - 60).toFixed(1)} ${(CROSS[1] - 80).toFixed(1)} ${CROSS[0].toFixed(1)} ${CROSS[1].toFixed(1)}`

export const knitting: Icon = {
  name: 'knitting',
  frames: 180,
  line: LINE,
  extrude: EXT,
  still: 0,
  layers: [
    // the cone stands still; the yarn runs from its tip to where the needles cross
    {
      id: 'cone',
      p: CONE_AT,
      tilt: FACE,
      shapes: [
        { d: poly([[-24, -104], [24, -104], [70, 104], [-70, 104]], 12), fill: 'main', depth: 1 },
        { d: 'M-36 -40Q0 -30 34 -46M-48 6Q0 18 46 0M-60 54Q0 68 58 48', line: 3 },
        { d: rect(-14, -128, 28, 26, 4), fill: 'tint', depth: 0.5 },
      ],
    },
    { shapes: [{ d: YARN, line: 3, round: true }] },
    { id: 'knit', p: KNIT_AT, m: { ...wiggle, k: 0.7 }, shapes: [] },
    {
      id: 'swatch',
      parent: 'knit',
      tilt: FACE,
      a: PIVOT,
      p: PIVOT,
      m: { ...tossLag, at: 5, k: 0.6 },
      shapes: [
        { d: rect(-78, -62, 156, 128, 10), fill: 'gold', depth: 0.5 },
        { d: STITCHES, line: 3 },
      ],
    },
    {
      parent: 'knit',
      tilt: FACE,
      shapes: [
        { d: needle([-104, -52], [104, -92]), fill: 'grey', depth: 0.3 },
        { d: ellipse(-106, -52, 12, 12), fill: 'deep', depth: 0.4 },
        { d: needle([104, -52], [-104, -92]), fill: 'grey', depth: 0.3 },
        { d: ellipse(106, -52, 12, 12), fill: 'deep', depth: 0.4 },
      ],
    },
    glow('knit', [-120, -150], 22, glint(46, 100)),
    glow('knit', [84, -150], 18, glint(52, 92)),
  ],
}
