import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  isActive,
  isWanted,
  primeSeen,
  setWanted,
  systemNotify,
  takeUnseen,
} from "../lib/notifications";

/* ---------------------------------------------------------------------------
   Alerts.

   Two failure modes matter more than the happy path: announcing the same thing
   twice (which trains people to ignore alerts), and announcing a backlog on
   load (which does the same, faster). Both are pinned here.
   --------------------------------------------------------------------------- */

const fired: { title: string; body?: string; tag?: string }[] = [];

class FakeNotification {
  static permission: NotificationPermission = "granted";
  static requestPermission = vi.fn(async () => FakeNotification.permission);
  onclick: (() => void) | null = null;
  constructor(title: string, options?: NotificationOptions) {
    fired.push({ title, body: options?.body, tag: options?.tag });
  }
  close() {}
}

const item = (id: number, over: Partial<Record<string, unknown>> = {}) => ({
  id,
  title: `Quotation Q-${id}`,
  body: "ready for review",
  link: `/quotations/${id}`,
  kind: "QUOTATION_READY",
  ...over,
});

beforeEach(() => {
  fired.length = 0;
  FakeNotification.permission = "granted";
  vi.stubGlobal("Notification", FakeNotification);
});

describe("preference", () => {
  it("is on by default, so a desk is told about work", () => {
    expect(isWanted()).toBe(true);
    expect(isActive()).toBe(true);
  });

  it("stays off once explicitly turned off", () => {
    setWanted(false);
    expect(isWanted()).toBe(false);
    expect(isActive()).toBe(false);
  });

  it("is inactive when the browser refuses, however much it is wanted", () => {
    FakeNotification.permission = "denied";
    expect(isWanted()).toBe(true);
    expect(isActive()).toBe(false);
  });
});

describe("takeUnseen", () => {
  it("returns each item exactly once, across calls", () => {
    expect(takeUnseen([item(1), item(2)])).toHaveLength(2);
    expect(takeUnseen([item(1), item(2)])).toHaveLength(0);
    expect(takeUnseen([item(2), item(3)])).toHaveLength(1);
  });

  it("survives a reload, because seen ids are persisted", () => {
    takeUnseen([item(1)]);
    // A fresh module read of localStorage is what a reload amounts to here.
    expect(takeUnseen([item(1)])).toHaveLength(0);
    expect(localStorage.getItem("notif:seen")).toContain("1");
  });
});

describe("primeSeen", () => {
  it("records a backlog without announcing it", () => {
    primeSeen([item(1), item(2), item(3)]);
    expect(fired).toHaveLength(0);
    // ...and nothing from that backlog is announced later either.
    expect(takeUnseen([item(1), item(2), item(3)])).toHaveLength(0);
  });
});

describe("systemNotify", () => {
  it("raises one notification per item", () => {
    systemNotify([item(1), item(2)], () => {});
    expect(fired).toHaveLength(2);
    expect(fired[0].title).toBe("Quotation Q-1");
  });

  it("summarises a burst instead of stacking popups", () => {
    systemNotify([item(1), item(2), item(3), item(4), item(5)], () => {});
    expect(fired).toHaveLength(1);
    expect(fired[0].body).toContain("+4 more waiting");
  });

  it("tags by kind, so a repeat replaces rather than piles up", () => {
    systemNotify([item(1)], () => {});
    expect(fired[0].tag).toBe("steel-desk-QUOTATION_READY");
  });

  it("stays silent when the user turned alerts off", () => {
    setWanted(false);
    systemNotify([item(1)], () => {});
    expect(fired).toHaveLength(0);
  });

  it("stays silent when the browser denied permission", () => {
    FakeNotification.permission = "denied";
    systemNotify([item(1)], () => {});
    expect(fired).toHaveLength(0);
  });

  it("routes to the item's link when clicked", () => {
    const navigate = vi.fn();
    vi.stubGlobal("window", { ...window, focus: vi.fn() });

    let captured: FakeNotification | null = null;
    vi.stubGlobal(
      "Notification",
      class extends FakeNotification {
        constructor(title: string, options?: NotificationOptions) {
          super(title, options);
          captured = this as unknown as FakeNotification;
        }
      },
    );

    systemNotify([item(7)], navigate);
    captured!.onclick?.();
    expect(navigate).toHaveBeenCalledWith("/quotations/7");
  });

  it("does not throw when the browser refuses to construct one", () => {
    vi.stubGlobal(
      "Notification",
      class {
        static permission = "granted";
        constructor() {
          throw new Error("refused");
        }
      },
    );
    // The bell and the toast still have it; a refusal must not break the poll.
    expect(() => systemNotify([item(1)], () => {})).not.toThrow();
  });
});
