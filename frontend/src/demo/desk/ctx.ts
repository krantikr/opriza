import type { LinkView } from "../components/LinkOverlay";
import type { DemoState, Outcome, ThreadId } from "../engine/types";
import type { BucketKey } from "./select";

export type Page = "home" | "inbox" | "sales" | "collect" | "customers" | "stock" | "cash" | "reports" | "agents" | "settings";

export type Role = "owner" | "accounts" | "sales" | "purchase";

export const ROLES: { id: Role; label: string }[] = [
  { id: "owner", label: "Owner" },
  { id: "accounts", label: "Accounts" },
  { id: "sales", label: "Sales" },
  { id: "purchase", label: "Purchase" },
];

/** Where a screen can be opened at, e.g. Collections filtered to 30+ days. */
export type PageParams = { tab?: string; bucket?: BucketKey; grade?: string; report?: string };

export type DrawerView = { type: "customer"; id: string } | { type: "quote"; no: string } | { type: "product"; idx: number };

/** Everything a desk screen needs from the shell. */
export type Ctx = {
  s: DemoState;
  role: Role;
  run: (o: Outcome) => void;
  set: (fn: (s: DemoState) => DemoState) => void;
  go: (p: Page, params?: PageParams) => void;
  drawer: (d: DrawerView | null) => void;
  /** Opens the floating chat on an agent, optionally asking it something. */
  chat: (thread: ThreadId, question?: string) => void;
  toast: (text: string) => void;
  link: (v: LinkView) => void;
};
