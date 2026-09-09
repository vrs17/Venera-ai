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
  return new Blob([encodeWavBytes(await renderTo16k(decoded), TARGET_RATE)], { type: 'audio/wav' })
}

/** Resample raw mono samples captured at `sampleRate` to 16 kHz.
 *
 *  Same path as `toWav16k`, on purpose: the voice panel's recordings go
 *  through exactly this and are the one capture route proven to transcribe.
 *  Asking the browser for a 16 kHz AudioContext instead would resample the
 *  LIVE microphone stream — a step Firefox refuses outright (it throws on a
 *  rate mismatch) and that the panel never takes. */
export async function resampleTo16k(samples: Float32Array, sampleRate: number): Promise<Float32Array> {
  if (sampleRate === TARGET_RATE) return samples
  const frames = Math.max(1, Math.ceil((samples.length / sampleRate) * TARGET_RATE))
  const offline = new OfflineAudioContext(1, frames, TARGET_RATE)
  const buffer = offline.createBuffer(1, samples.length, sampleRate)
  buffer.getChannelData(0).set(samples)
  return renderTo16k(buffer, offline)
}

/** Renders any AudioBuffer to mono 16 kHz. OfflineAudioContext does the
 *  resampling (and the channel downmix, since the destination is mono) with
 *  the browser's own filter — far better than hand-rolled interpolation. */
async function renderTo16k(buffer: AudioBuffer, offline?: OfflineAudioContext): Promise<Float32Array> {
  const frames = Math.max(1, Math.ceil(buffer.duration * TARGET_RATE))
  const ctx = offline ?? new OfflineAudioContext(1, frames, TARGET_RATE)
  const source = ctx.createBufferSource()
  source.buffer = buffer
  source.connect(ctx.destination)
  source.start(0)
  const rendered = await ctx.startRendering()
  return rendered.getChannelData(0)
}
