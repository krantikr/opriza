import type { ThreadId } from "../engine/types";

/** The problems a visitor can tick. Each one points at the chat that solves
 *  it, so the demo opens with those chats on top and already busy. */
export type Problem = {
  id: string;
  title: string;
  detail: string;
  thread: ThreadId;
  /** Short label for chips and the setup summary. */
  short: string;
};

export const PROBLEMS: Problem[] = [
  {
    id: "quotes",
    title: "Quotes take hours",
    detail: "Customers buy from whoever replies first.",
    thread: "sales",
    short: "Slow quotes",
  },
  {
    id: "approvals",
    title: "Every price waits for me",
    detail: "My team can't quote without calling me.",
    thread: "brief",
    short: "Owner approves everything",
  },
  {
    id: "collections",
    title: "Money is stuck with customers",
    detail: "Follow-ups depend on someone remembering.",
    thread: "collect",
    short: "Late payments",
  },
  {
    id: "stock",
    title: "Stock-outs and dead stock",
    detail: "Fast items run out, slow ones sit for months.",
    thread: "stock",
    short: "Stock planning",
  },
  {
    id: "cash",
    title: "Cash gets tight without warning",
    detail: "I find out when a supplier payment is due.",
    thread: "cash",
    short: "Cash flow",
  },
  {
    id: "answers",
    title: "Simple answers need my accountant",
    detail: "Tally has the data, but I can't get to it quickly.",
    thread: "ask",
    short: "Getting answers",
  },
  {
    id: "risk",
    title: "I give credit to the wrong customers",
    detail: "I only learn who pays late after it's too late.",
    thread: "score",
    short: "Credit risk",
  },
];
