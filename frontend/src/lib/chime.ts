/* The notification sound.
 *
 * Synthesised with the WebAudio API rather than shipped as an mp3. A two-tone
 * chime is a few lines of oscillator, and the alternative - an audio file -
 * costs a network request, a decode, and a binary in the repository that
 * nobody can diff. It also lets each tone carry its own pitch, so a trader
 * learns to tell a settled quotation from a failure without looking up.
 *
 * Everything here is best-effort. Browsers refuse to make noise until the
 * user has interacted with the page, some devices have no audio at all, and
 * an office may simply have the volume down. None of that is an error worth
 * surfacing: a notification that arrives silently is still a notification, so
 * every failure path returns quietly instead of throwing.
 */

export type ChimeTone = "info" | "settled" | "attention" | "danger";

/** Two notes per tone, in Hz.
 *
 *  Rising intervals for good news, falling for bad - the same convention a
 *  doorbell and an error beep already use, so it needs no explaining. Kept
 *  inside one octave around A5 to stay mild: the brief is a chime, not an
 *  alarm, and this plays on a desk where people are working. */
const NOTES: Record<ChimeTone, [number, number]> = {
  settled: [660, 880], // rising major third - resolved
  info: [740, 740], // flat, unremarkable
  attention: [660, 560], // gently falling - something needs a look
  danger: [560, 420], // falling further - something is wrong
};

let context: AudioContext | null = null;

/** One AudioContext for the tab, created on first use.
 *
 *  Constructing one per chime leaks: browsers cap how many a page may hold,
 *  and a busy morning would hit that cap and go silent for the rest of the
 *  session. */
function audio(): AudioContext | null {
  try {
    const Ctor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return null;
    context ??= new Ctor();
    // Autoplay policy parks the context until a gesture; a resume here is what
    // makes the first chime after a click audible rather than swallowed.
    if (context.state === "suspended") void context.resume();
    return context;
  } catch {
    return null;
  }
}

/** Play one note as a short, soft sine with an eased fade.
 *
 *  The fade matters more than the pitch: a square wave cut off abruptly clicks
 *  audibly, which reads as a glitch rather than a chime. */
function note(ctx: AudioContext, hz: number, startAt: number, seconds: number, peak: number) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();

  osc.type = "sine";
  osc.frequency.setValueAtTime(hz, startAt);

  gain.gain.setValueAtTime(0.0001, startAt);
  gain.gain.exponentialRampToValueAtTime(peak, startAt + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, startAt + seconds);

  osc.connect(gain).connect(ctx.destination);
  osc.start(startAt);
  osc.stop(startAt + seconds + 0.02);
}

/** A short two-note chime for `tone`. Silent and safe if audio is unavailable. */
export function playChime(tone: ChimeTone): void {
  const ctx = audio();
  if (!ctx) return;

  try {
    const [first, second] = NOTES[tone];
    const now = ctx.currentTime;
    // Audible across a desk without being startling. The first values here
    // were tuned on headphones and turned out to be inaudible over an office
    // - a chime nobody hears is the same as no chime, and the trader ends up
    // watching the screen instead, which is what the sound existed to avoid.
    //
    // Still bounded well under 1.0: this is a chime under conversation, not
    // an alarm, and a notification that makes people flinch gets muted
    // permanently - at which point it is worth nothing again.
    const peak = tone === "danger" ? 0.22 : 0.16;

    note(ctx, first, now, 0.18, peak);
    note(ctx, second, now + 0.14, 0.28, peak);
  } catch {
    // An audio failure must never take a notification down with it.
  }
}
