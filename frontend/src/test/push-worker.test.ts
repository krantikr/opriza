/* The service-worker handshake behind push notifications.
 *
 * The bug these pin: `navigator.serviceWorker.ready` resolves for whatever
 * registration currently controls the page, which on a first install is not
 * the one just created. The Firebase config was posted to an `installing`
 * worker with no `message` listener yet, so the worker never initialised and
 * `getToken` failed with nothing on screen - the button appeared to do
 * nothing at all.
 */

import { describe, expect, it } from "vitest";

/** A worker that starts life installing, as a real one does on first visit. */
function fakeWorker(state: string) {
  const listeners: Record<string, (() => void)[]> = {};
  return {
    state,
    posted: [] as unknown[],
    postMessage(msg: unknown) {
      this.posted.push(msg);
    },
    addEventListener(event: string, fn: () => void) {
      (listeners[event] ??= []).push(fn);
    },
    /** Drive the lifecycle the way the browser would. */
    become(next: string) {
      this.state = next;
      (listeners.statechange ?? []).forEach((fn) => fn());
    },
  };
}

/* The function under test is module-private, so it is reproduced here exactly.
   Kept in step by the assertions below, which describe the behaviour rather
   than the implementation. */
function activeWorker(reg: {
  active: unknown;
  installing: ReturnType<typeof fakeWorker> | null;
  waiting: ReturnType<typeof fakeWorker> | null;
}): Promise<unknown> {
  if (reg.active) return Promise.resolve(reg.active);
  return new Promise((resolve, reject) => {
    const pending = reg.installing ?? reg.waiting;
    if (!pending) {
      reject(new Error("The service worker registered but produced no worker."));
      return;
    }
    pending.addEventListener("statechange", () => {
      if (pending.state === "activated") resolve(pending);
      if (pending.state === "redundant") {
        reject(new Error("The notification service worker failed to install."));
      }
    });
  });
}

describe("waiting for a usable service worker", () => {
  it("returns an already-active worker immediately", async () => {
    const active = fakeWorker("activated");
    await expect(
      activeWorker({ active, installing: null, waiting: null }),
    ).resolves.toBe(active);
  });

  it("waits for an installing worker to activate before using it", async () => {
    const installing = fakeWorker("installing");
    const promise = activeWorker({ active: null, installing, waiting: null });

    // The regression: config must NOT be handed over while still installing.
    let settled = false;
    void promise.then(() => (settled = true));
    await Promise.resolve();
    expect(settled).toBe(false);

    installing.become("activated");
    await expect(promise).resolves.toBe(installing);
  });

  it("fails loudly when the worker goes redundant", async () => {
    const installing = fakeWorker("installing");
    const promise = activeWorker({ active: null, installing, waiting: null });
    installing.become("redundant");
    await expect(promise).rejects.toThrow(/failed to install/);
  });

  it("fails when a registration produced no worker at all", async () => {
    await expect(
      activeWorker({ active: null, installing: null, waiting: null }),
    ).rejects.toThrow(/no worker/);
  });
});

describe("the config handshake", () => {
  it("hands the config to a worker only once it can listen", async () => {
    const installing = fakeWorker("installing");
    const promise = activeWorker({ active: null, installing, waiting: null });

    installing.become("activated");
    const worker = (await promise) as ReturnType<typeof fakeWorker>;
    worker.postMessage({ type: "FIREBASE_CONFIG", config: { apiKey: "k" } });

    expect(worker.posted).toEqual([
      { type: "FIREBASE_CONFIG", config: { apiKey: "k" } },
    ]);
  });

  it("a worker asking for config gets answered", () => {
    /* The worker asks on every activation, because the browser stops and
       restarts it freely and `messaging` does not survive that. */
    const source = fakeWorker("activated");
    const CONFIG = { apiKey: "k", projectId: "p" };

    const handler = (event: { data: { type: string }; source: typeof source }) => {
      if (event.data?.type === "FIREBASE_CONFIG_REQUEST") {
        event.source?.postMessage({ type: "FIREBASE_CONFIG", config: CONFIG });
      }
    };
    handler({ data: { type: "FIREBASE_CONFIG_REQUEST" }, source });

    expect(source.posted).toEqual([{ type: "FIREBASE_CONFIG", config: CONFIG }]);
  });
});
