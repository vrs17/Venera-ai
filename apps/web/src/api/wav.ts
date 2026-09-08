// Turn whatever MediaRecorder produced into 16 kHz mono 16-bit PCM WAV.
//
// Why: the STT router's Uzbek backend accepts only .wav/.ogg/.opus/.mp3/.flac
// and cannot decode WebM at all, while Chrome and Edge can only RECORD WebM.
// Converting in the browser removes the mismatch for every route and every
// browser, with no server-side transcoder. 16 kHz mono is what the models
// consume anyway; a 30 s turn is ~960 KB.

/** Pure encoder — no DOM, so it can be unit-tested in Node. */
// Return type is pinned to `Uint8Array<ArrayBuffer>`: with TS 5.7+ a bare
// `Uint8Array` means `<ArrayBufferLike>`, which `new Blob([...])` refuses.
export function encodeWavBytes(samples: Float32Array, sampleRate: number): Uint8Array<ArrayBuffer> {
  const bytesPerSample = 2
  const dataSize = samples.length * bytesPerSample
  const buffer = new ArrayBuffer(44 + dataSize)
  const view = new DataView(buffer)
  const ascii = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i))
  }
  ascii(0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  ascii(8, 'WAVE')
  ascii(12, 'fmt ')
  view.setUint32(16, 16, true)            // fmt chunk size
  view.setUint16(20, 1, true)             // PCM
  view.setUint16(22, 1, true)             // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * bytesPerSample, true) // byte rate
  view.setUint16(32, bytesPerSample, true) // block align
  view.setUint16(34, 16, true)            // bits per sample
  ascii(36, 'data')
  view.setUint32(40, dataSize, true)
  let offset = 44
  for (let i = 0; i < samples.length; i++, offset += 2) {
    // Clamp: decoded audio can overshoot [-1, 1] slightly.
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Uint8Array(buffer)
}

export const TARGET_RATE = 16000

/** Decode a recorded blob, downmix to mono, resample to 16 kHz, encode WAV.
 *  Throws if the browser cannot decode the container — callers fall back to
 *  sending the original blob. */
export async function toWav16k(blob: Blob): Promise<Blob> {
  const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Ctx) throw new Error('AudioContext unavailable')
  const ctx = new Ctx()
  let decoded: AudioBuffer
  try {
    decoded = await ctx.decodeAudioData(await blob.arrayBuffer())
  } finally {
    void ctx.close()
  }
  const frames = Math.max(1, Math.ceil(decoded.duration * TARGET_RATE))
  // OfflineAudioContext does the resampling (and the channel downmix, since
  // the destination is mono) with the browser's own filter — far better than
  // hand-rolled linear interpolation.
  const offline = new OfflineAudioContext(1, frames, TARGET_RATE)
  const source = offline.createBufferSource()
  source.buffer = decoded
  source.connect(offline.destination)
  source.start(0)
  const rendered = await offline.startRendering()
  return new Blob([encodeWavBytes(rendered.getChannelData(0), TARGET_RATE)], { type: 'audio/wav' })
}
