import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  onSoundPreferenceChange,
  setSoundEnabled,
  soundEnabled,
} from "../lib/sound-preference";

/* ---------------------------------------------------------------------------
   The notification sound preference.

   Two things matter here beyond the obvious round-trip. Sound must default to
   *on* for someone who has never chosen - a chime nobody hears is a
   notification nobody acts on. And every read must survive a browser that
   throws on localStorage access, because private windows and blocked site data
   do exactly that, and a missing preference must never take notifications down
   with it.
   --------------------------------------------------------------------------- */

const KEY = "steeldesk.notification-sound";

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("sound preference", () => {
  it("is on for someone who has never chosen", () => {
    expect(soundEnabled()).toBe(true);
  });

  it("remembers being turned off", () => {
    setSoundEnabled(false);
    expect(soundEnabled()).toBe(false);
    expect(localStorage.getItem(KEY)).toBe("off");
  });

  it("remembers being turned back on", () => {
    setSoundEnabled(false);
    setSoundEnabled(true);
    expect(soundEnabled()).toBe(true);
  });

  it("stays on when the browser refuses to read storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("The operation is insecure.");
    });
    // A private window must still get notifications, just unremembered ones.
    expect(soundEnabled()).toBe(true);
  });

  it("does not throw when the browser refuses to write storage", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    expect(() => setSoundEnabled(false)).not.toThrow();
  });

  it("tells listeners so Settings and the toasts never disagree", () => {
    const seen: boolean[] = [];
    const stop = onSoundPreferenceChange((on) => seen.push(on));

    setSoundEnabled(false);
    setSoundEnabled(true);
    stop();
    setSoundEnabled(false);

    // The third change lands after unsubscribing and must not be reported.
    expect(seen).toEqual([false, true]);
  });
});
