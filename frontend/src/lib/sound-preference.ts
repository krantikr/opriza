/* Whether notifications make a sound on this device.
 *
 * Deliberately per-device rather than per-account. The same trader wants the
 * chime on their phone and off on the desk machine in a shared office, and a
 * server-side preference would force one answer onto both. localStorage is
 * exactly the right scope for that, and it survives a reload.
 *
 * Default is on: someone who has enabled push has asked to be interrupted,
 * and a chime nobody hears is a notification nobody acts on. It is one click
 * to silence in Settings.
 */

const KEY = "steeldesk.notification-sound";

/** Subscribers re-render when the preference changes.
 *
 *  Settings and the toast layer read the same value from different corners of
 *  the tree, so a plain read would leave the toggle showing one thing while
 *  the toasts do another. */
const listeners = new Set<(on: boolean) => void>();

export function soundEnabled(): boolean {
  try {
    // Absent means "never chose", which is on.
    return localStorage.getItem(KEY) !== "off";
  } catch {
    // Private windows and blocked site data throw on access rather than
    // returning null, and a missing preference must not break notifications.
    return true;
  }
}

export function setSoundEnabled(on: boolean): void {
  try {
    localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    // Preference is lost on reload, but the session still honours it below.
  }
  for (const listener of listeners) listener(on);
}

export function onSoundPreferenceChange(listener: (on: boolean) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
