// The spoken greeting, prepared ahead of time.
//
// WHY A FILE AND NOT A TTS CALL. The greeting never changes, synthesis costs
// ~2 s, and it queues behind every other request on the single TTS GPU. Someone
// who says "Salom Venera" should hear an answer immediately, not watch a
// spinner — and burning a GPU slot on a fixed sentence, every time, for every
// user, is waste. The file is built once by `apps/api/tools/make_greeting.py`
// and cached by the browser like any other asset.
//
// Regenerate it whenever `voiceGreeting` changes; the two must say the same
// thing, because one is read on screen and the other out loud.

import greetingUrl from '../assets/greeting-uz.wav'

/** Locales the prepared file speaks for. The recording is Uzbek; a Cyrillic
 *  reader hears the same words, which is correct — the script differs, the
 *  language does not.
 *
 *  EMPTY for now: the product was renamed Venera -> Barno, and the current
 *  greeting-uz.wav still says "Men Venera". Until it is regenerated with
 *  `make_greeting.py` (its GREETING already says Barno), `uz` falls back to
 *  live synthesis of `voiceGreeting` — ~2 s slower, but it says the right
 *  name; `uz-Cyrl` has no live voice (see `canSpeak`) and opens silently.
 *  After regenerating, put ['uz', 'uz-Cyrl'] back. */
const PREPARED: readonly string[] = []

let cached: Blob | null = null

/**
 * The prepared greeting, or null if there is none for this locale or it could
 * not be fetched. Null means "fall back to live synthesis" — a missing asset
 * must degrade to the slow path, never to silence.
 */
export async function preparedGreeting(locale: string): Promise<Blob | null> {
  if (!PREPARED.includes(locale)) return null
  if (cached) return cached
  try {
    const response = await fetch(greetingUrl, { cache: 'force-cache' })
    if (!response.ok) return null
    // The type is forced rather than taken from the response: nginx's stock
    // mime.types has no `.wav` entry at all, so a misconfigured or older
    // deployment serves this as application/octet-stream — and an <audio>
    // element may refuse a source whose type it does not recognise. We know
    // exactly what this file is.
    cached = new Blob([await response.arrayBuffer()], { type: 'audio/wav' })
    return cached
  } catch {
    return null
  }
}

/** Warms the browser cache so the first wake word plays without a fetch. Safe
 *  to call repeatedly; failures are ignored. */
export function warmGreeting(locale: string): void {
  void preparedGreeting(locale)
}
