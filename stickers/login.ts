// Entry for core/static/core/sticker.js — rebuild with: bun build stickers/login.ts --minify --target browser --outfile core/static/core/sticker.js
import { play } from './fun'
import { knitting } from './icons'

// SY OS colours on the sticker's palette slots
const SY = { main: '#2563eb', deep: '#1e40af', gold: '#f97316', tint: '#dbeaff', ok: '#16a34a', hot: '#ea580c', ink: '#0a0a0a', paper: '#f5f5f5' }

for (const c of document.querySelectorAll<HTMLCanvasElement>('canvas[data-sticker]')) play(c, knitting, { palette: SY, enter: 0.15 })
