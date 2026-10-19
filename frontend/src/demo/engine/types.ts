import type { IndustryPack } from "../data/industries";

/* ---------------------------------------------------------------------------
   What the visitor tells us
   --------------------------------------------------------------------------- */

export type RevenueBand = "50-100" | "100-250" | "250-500" | "500+";
export type Language = "English" | "Hinglish";

export type Business = {
  company: string;
  owner: string;
  city: string;
  industry: string;
  revenue: RevenueBand;
  team: string;
  tally: "TallyPrime" | "Tally.ERP 9";
  language: Language;
  problems: string[];
};

/* ---------------------------------------------------------------------------
   The mock business generated from it
   --------------------------------------------------------------------------- */

export type Product = {
  key: string;
  name: string;
  alias: string[];
  unit: string;
  rate: number;
  cost: number;
  stock: number;
  perDay: number;
  lastBuys: number[];
  qty: [number, number];
};

export type Grade = "A" | "B" | "C" | "D";

export type Bill = { no: string; date: Date; amount: number; daysLate: number };

export type Customer = {
  id: string;
  name: string;
  contact: string;
  phone: string;
  grade: Grade;
  outstanding: number;
  bills: Bill[];
  avgDelay: number;
  payDay: number;
  sales12m: number;
  lastBuyDays: number;
  promisesKept: number;
  promisesMade: number;
  since: number;
};

export type Supplier = { name: string; brand: string; onTime: number; delta: number; days: number };

export type World = {
  biz: Business;
  pack: IndustryPack;
  firstName: string;
  products: Product[];
  customers: Customer[];
  suppliers: Supplier[];
  team: { sales: string[]; accounts: string; purchase: string };
  limits: { marginFloor: number; maxDiscount: number; poLimit: number };
  kpi: {
    salesYesterday: number;
    vsAverage: number;
    salesMtd: number;
    mtdChange: number;
    receivable: number;
    overdue: number;
    overdueCount: number;
    dso: number;
    stockValue: number;
    idleValue: number;
    payables7: number;
    payables30: number;
    payablesCount: number;
    inThisWeek: number;
  };
  cash: { label: string; inflow: number; outflow: number }[];
  margins: { label: string; value: number }[];
  sales7: { label: string; value: number }[];
  today: Date;
};

/* ---------------------------------------------------------------------------
   Chats
   --------------------------------------------------------------------------- */

export type ThreadId = "brief" | "sales" | "collect" | "stock" | "cash" | "ask" | "score";

export type Tone = "good" | "bad" | "warn" | "info";

export type Kpi = { label: string; value: string; note?: string; tone?: Tone };

export type QuoteLine = { name: string; qty: number; unit: string; rate: number };

export type Card =
  | { kind: "brief"; kpis: Kpi[]; todo: { text: string; go: Go }[] }
  | { kind: "enquiry"; customer: string; contact: string; channel: string; text: string; fields: [string, string][] }
  | {
      kind: "quote";
      no: string;
      customer: string;
      grade: Grade;
      lines: QuoteLine[];
      freight: number;
      margin: number;
      inBand: boolean;
      status: "ready" | "sent" | "won" | "held" | "waiting";
      lastRate?: number;
      terms: string;
    }
  | { kind: "queue"; total: number; count: number; rows: { name: string; amount: number; tag: string; tone: Tone; hint: string }[] }
  | {
      kind: "due";
      customerId: string;
      name: string;
      grade: Grade;
      amount: number;
      daysLate: number;
      bills: number;
      habit: string;
      draft: string;
      language: Language;
    }
  | { kind: "reorder"; product: string; unit: string; stock: number; perDay: number; daysLeft: number; suggest: number; lastBuys: number[] }
  | {
      kind: "rates";
      product: string;
      qty: number;
      unit: string;
      rows: { supplier: string; brand: string; rate: number; days: number; onTime: number; best: boolean }[];
      note: string;
    }
  | { kind: "idle"; product: string; qty: number; unit: string; value: number; days: number; cost: number; market: number; offer: number; buyers: string[] }
  | { kind: "cashweeks"; weeks: { label: string; inflow: number; outflow: number }[] }
  | { kind: "alert"; tone: Tone; title: string; body: string }
  | { kind: "table"; title?: string; cols: string[]; rows: string[][]; align?: ("l" | "r")[]; footnote?: string }
  | { kind: "bars"; title: string; unit?: string; bars: { label: string; value: number; display: string }[]; highlight: number; footnote?: string }
  | { kind: "kpis"; title?: string; kpis: Kpi[] }
  | { kind: "score"; name: string; grade: Grade; from: Grade; reasons: { up: boolean; text: string }[]; suggestion: string }
  | { kind: "won"; customer: string; amount: number; quoteNo: string; minutes: number; posted: boolean }
  | { kind: "po"; no: string; supplier: string; product: string; qty: number; unit: string; rate: number; status: "draft" | "waiting" | "posted" };

/** Where a tap can take the visitor. */
export type Go =
  | { to: "thread"; id: ThreadId }
  | { to: "tab"; tab: Tab };

export type Tab = "chats" | "approvals" | "today" | "settings";

export type Action = {
  id: string;
  label: string;
  primary?: boolean;
  /** Free data the handler needs, e.g. the customer id or a chosen date. */
  data?: Record<string, string | number>;
};

export type Msg = {
  id: string;
  from: "agent" | "me" | "system";
  at: number;
  text?: string;
  card?: Card;
  actions?: Action[];
  /** Quick replies shown as chips under the message. */
  chips?: Action[];
  /** Label of the action already taken; the other buttons go quiet. */
  chosen?: string;
  /** The footnote under an agent message, e.g. "Sent to customer". */
  status?: string;
};

export type Thread = {
  id: ThreadId;
  name: string;
  sub: string;
  letter: string;
  bg: string;
  fg: string;
  messages: Msg[];
  unread: number;
  typing: boolean;
  /** Suggested questions shown above the composer. */
  suggestions: string[];
};

export type Approval = {
  id: string;
  type: string;
  who: string;
  title: string;
  detail: string;
  why: string;
  thread: ThreadId;
  after: string;
  status: "waiting" | "approved" | "changed";
  ref?: string;
};

export type DemoState = {
  world: World;
  threads: Record<ThreadId, Thread>;
  order: ThreadId[];
  approvals: Approval[];
  clock: number;
  seq: { quote: number; po: number };
  collectedToday: number;
  wonToday: number;
  queueIndex: number;
};

/** A UI side effect an agent reply asks for. */
export type UiEffect =
  | { type: "openThread"; id: ThreadId }
  | { type: "tab"; tab: Tab }
  | { type: "customerQuote"; thread: ThreadId; msgId: string }
  | { type: "customerStatement"; customerId: string }
  | { type: "supplierRate"; product: string }
  | { type: "toast"; text: string };

/** What a tap or a question produces. `now` runs at once; each `later`
 *  step shows the agent typing for `delay` ms and then lands. */
export type Outcome = {
  now?: (s: DemoState) => DemoState;
  later?: { delay: number; thread: ThreadId; run: (s: DemoState) => DemoState }[];
  ui?: UiEffect;
};
