import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChimeTone } from "../lib/chime";

/* ---------------------------------------------------------------------------
   The notification chime.

   There is nothing to assert about how it *sounds*, so these tests pin the
   only thing that can actually break a desk: a notification must arrive even
   when the sound cannot. Browsers block audio before a user gesture, some
   devices have no output at all, and jsdom has no AudioContext whatsoever -
   none of which is a reason for a trader to miss an enquiry.
   --------------------------------------------------------------------------- */

/** A fresh copy of the module.
 *
 *  `chime.ts` caches one AudioContext per tab on purpose, so without this the
 *  first test's stub would still be in place for every later one. */
async function freshPlayChime(): Promise<(tone: ChimeTone) => void> {
  vi.resetModules();
  return (await import("../lib/chime")).playChime;
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("playChime", () => {
  it("stays silent rather than throwing where there is no audio at all", async () => {
    const playChime = await freshPlayChime();
    // jsdom's default: window.AudioContext is undefined.
    expect(() => playChime("settled")).not.toThrow();
  });

  it("does not throw when constructing the audio context fails", async () => {
    vi.stubGlobal(
      "AudioContext",
      class {
        constructor() {
          throw new Error("not allowed");
        }
      },
    );
    const playChime = await freshPlayChime();
    expect(() => playChime("danger")).not.toThrow();
  });

  it("resumes a context the autoplay policy has parked", async () => {
    const resume = vi.fn();
    vi.stubGlobal(
      "AudioContext",
      class {
        state = "suspended";
        currentTime = 0;
        destination = {};
        resume = resume;
        createOscillator() {
          return {
            type: "",
            frequency: { setValueAtTime: vi.fn() },
            connect: () => ({ connect: vi.fn() }),
            start: vi.fn(),
            stop: vi.fn(),
          };
        }
        createGain() {
          return {
            gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
            connect: () => ({ connect: vi.fn() }),
          };
        }
      },
    );

    const playChime = await freshPlayChime();
    playChime("info");

    // Without this the first chime after a page load is swallowed silently.
    expect(resume).toHaveBeenCalled();
  });

  it("plays two notes per chime", async () => {
    const started: number[] = [];
    vi.stubGlobal(
      "AudioContext",
      class {
        state = "running";
        currentTime = 0;
        destination = {};
        createOscillator() {
          return {
            type: "",
            frequency: { setValueAtTime: vi.fn() },
            connect: () => ({ connect: vi.fn() }),
            start: (at: number) => started.push(at),
            stop: vi.fn(),
          };
        }
        createGain() {
          return {
            gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
            connect: () => ({ connect: vi.fn() }),
          };
        }
      },
    );

    const playChime = await freshPlayChime();
    playChime("attention");

    // Two tones, the second offset - a single note reads as a system beep.
    expect(started).toHaveLength(2);
    expect(started[1]).toBeGreaterThan(started[0]);
  });
});
