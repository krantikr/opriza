import { createContext, useContext } from "react";

import type { Me, Role } from "./data";

export type Page = "home" | "inbox" | "sales" | "collect" | "customers" | "stock" | "cash" | "reports" | "agents" | "settings";

export const ROLES: { id: Role; label: string }[] = [
  { id: "owner", label: "Owner" },
  { id: "accounts", label: "Accounts" },
  { id: "sales", label: "Sales" },
  { id: "purchase", label: "Purchase" },
];

export type DrawerView = { type: "customer"; id: number } | { type: "quote"; id: number } | { type: "item"; id: number };

export type Ctx = {
  me: Me;
  role: Role;
  go: (p: Page, params?: Record<string, string>) => void;
  params: Record<string, string>;
  drawer: (d: DrawerView | null) => void;
  /** Opens the chat on an agent, optionally asking it something. */
  chat: (thread: string, question?: string) => void;
  toast: (text: string) => void;
  /** Run a change, then refresh every screen. Returns the result, or null on error (already shown). */
  act: <T>(fn: () => Promise<T>, done?: string | ((r: T) => string)) => Promise<T | null>;
};

export const DeskContext = createContext<Ctx | null>(null);

export function useDesk(): Ctx {
  const c = useContext(DeskContext);
  if (!c) throw new Error("useDesk outside the desk");
  return c;
}
