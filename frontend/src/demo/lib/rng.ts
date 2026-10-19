/** A small seeded random generator, so the same business details always
 *  produce the same demo. A visitor who refreshes, or shows a colleague,
 *  sees the same customers and numbers instead of a reshuffle. */

export type Rng = () => number;

export function seedFrom(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** mulberry32: tiny, fast, and good enough for mock data. */
export function makeRng(seed: number): Rng {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const between = (r: Rng, lo: number, hi: number) => lo + (hi - lo) * r();
export const intBetween = (r: Rng, lo: number, hi: number) => Math.floor(between(r, lo, hi + 1));

export function pick<T>(r: Rng, list: readonly T[]): T {
  return list[Math.floor(r() * list.length)] as T;
}

export function shuffle<T>(r: Rng, list: readonly T[]): T[] {
  const out = [...list];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(r() * (i + 1));
    [out[i], out[j]] = [out[j] as T, out[i] as T];
  }
  return out;
}
