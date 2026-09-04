// Copy helper. The async Clipboard API only exists in secure contexts
// (HTTPS / localhost); over plain HTTP on the LAN it's undefined — the same
// constraint that bites crypto.randomUUID in ChatView — so we fall back to a
// hidden-textarea execCommand('copy'). Returns whether the copy succeeded.

export async function copyText(text: string): Promise<boolean> {
  if (!text) return false

  // Preferred path: async Clipboard API (secure contexts only).
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* permission denied or unavailable — fall through to the legacy path */
  }

  // Fallback: a transient off-screen textarea + execCommand.
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    // Keep it out of view and out of the layout/scroll flow.
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '0'
    ta.style.left = '0'
    ta.style.width = '1px'
    ta.style.height = '1px'
    ta.style.padding = '0'
    ta.style.border = 'none'
    ta.style.opacity = '0'
    ta.style.pointerEvents = 'none'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    ta.setSelectionRange(0, text.length)
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
