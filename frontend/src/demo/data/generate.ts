import { addDays, monthName } from "../lib/format";
import { between, intBetween, makeRng, pick, seedFrom, shuffle } from "../lib/rng";
import type { Bill, Business, Customer, Grade, Product, RevenueBand, World } from "../engine/types";
import { industryById } from "./industries";

/** Annual sales, in rupees, at the middle of each band. */
const ANNUAL: Record<RevenueBand, number> = {
  "50-100": 75e7,
  "100-250": 175e7,
  "250-500": 375e7,
  "500+": 650e7,
};

const STEMS = ["Shree", "Om Sai", "Mehta", "Kalyan", "Patel", "Deccan", "Balaji", "Ganesh", "Vardhman", "Laxmi", "Siddhi", "Raj", "Krishna", "Jai Hind", "Bharat", "Sunrise"];
const CONTACTS = ["Rajesh", "Suresh", "Amit", "Vikram", "Pradeep", "Manoj", "Anil", "Nitin", "Sanjay", "Rakesh", "Deepak", "Mahesh", "Prakash", "Ashok"];
const TEAM = ["Amit", "Priya", "Rohan", "Neha", "Sunil", "Kavita", "Imran", "Pooja"];
/** More name stems for the long tail of smaller customers a desk table shows. */
const MORE_STEMS = ["Annapurna", "Shiv Shakti", "Navkar", "Samarth", "Mahalaxmi", "Tirupati", "Sai Kripa", "Gurukrupa", "Ambika", "Jay Ambe", "Shubham", "Swastik", "Vinayak", "Hari Om", "Sri Ram", "Neelkanth", "Prime", "Unity", "Royal", "Surya", "Venkatesh", "Matoshree", "Kaveri", "Narmada", "Galaxy", "Pioneer", "Trimurti", "Omkar", "Akshar", "Yash"];
const AREAS = ["MIDC", "Ring Road", "Station Road", "Old City", "Industrial Estate", "Highway", "New Town", "Market Yard"];
/** How many customers the mock business has in total. */
const CUSTOMER_COUNT = 40;

/** Rounds a quantity to something a trader would actually order. */
export function roundQty(n: number, unit: string): number {
  if (["MT", "barrel", "bucket"].includes(unit)) return Math.max(1, Math.round(n));
  if (n >= 10000) return Math.round(n / 500) * 500;
  if (n >= 1000) return Math.round(n / 100) * 100;
  if (n >= 100) return Math.round(n / 10) * 10;
  return Math.max(1, Math.round(n));
}

function roundRate(n: number): number {
  if (n >= 10000) return Math.round(n / 100) * 100;
  if (n >= 1000) return Math.round(n / 10) * 10;
  if (n >= 100) return Math.round(n);
  return Math.round(n * 10) / 10;
}

function roundMoney(n: number): number {
  return n >= 1e6 ? Math.round(n / 1e4) * 1e4 : Math.round(n / 100) * 100;
}

export function firstNameOf(owner: string): string {
  const name = owner.trim().split(/\s+/)[0] ?? "";
  return name || "there";
}

/** Builds the whole mock business from the visitor's answers. Same answers,
 *  same business, every time. */
export function buildWorld(biz: Business, today = new Date()): World {
  const r = makeRng(seedFrom(`${biz.company}|${biz.industry}|${biz.city}|${biz.revenue}`));
  const pack = industryById(biz.industry);
  const annual = ANNUAL[biz.revenue] * between(r, 0.9, 1.1);
  const perDaySales = annual / 300;

  /* --- products -------------------------------------------------------- */
  const shares = [0.24, 0.18, 0.14, 0.11, 0.08, 0.05];
  const coverDays = [9, 17, 24, 31, 38, 45];
  const products: Product[] = pack.products.map((p, i) => {
    const rate = roundRate(p.rate * between(r, 0.98, 1.02));
    const marginPct = between(r, 3.6, 5.8);
    const cost = roundRate(rate * (1 - marginPct / 100));
    const perDayRaw = (perDaySales * (shares[i] ?? 0.05)) / rate;
    const perDay = perDayRaw >= 20 ? Math.round(perDayRaw) : Math.max(1, Math.round(perDayRaw * 10) / 10);
    const stock = roundQty(perDay * (coverDays[i] ?? 40), p.unit);
    const lastBuys = [0, 1, 2].map(() => roundRate(cost * between(r, 0.985, 1.015)));
    return { key: `p${i}`, name: p.name, alias: p.alias, unit: p.unit, rate, cost, stock, perDay, lastBuys, qty: p.qty };
  });

  /* --- receivables and customers -------------------------------------- */
  const dso = intBetween(r, 52, 68);
  const receivable = roundMoney((annual * dso) / 365);
  const overdue = roundMoney(receivable * between(r, 0.3, 0.38));
  const overdueCount = intBetween(r, 11, 19);
  const base = overdue / overdueCount;

  const stems = shuffle(r, STEMS);
  const kinds = shuffle(r, pack.customerKinds);
  const weights = [2.6, 1.7, 1.35, 1.05, 0.85, 0.7, 0.55, 0.45, 0.4, 0.35];
  const grades: Grade[] = ["C", "B", "B", "A", "C", "B", "A", "D", "B", "A"];
  const customers: Customer[] = weights.map((w, i) => {
    const amount = roundMoney(base * w * between(r, 0.9, 1.1));
    const grade = grades[i] as Grade;
    const late = grade === "A" ? intBetween(r, 0, 4) : grade === "B" ? intBetween(r, 3, 9) : grade === "C" ? intBetween(r, 12, 22) : intBetween(r, 25, 40);
    const nBills = amount > base * 1.2 ? 3 : 2;
    const bills: Bill[] = [];
    let left = amount;
    for (let b = 0; b < nBills; b++) {
      const part = b === nBills - 1 ? left : roundMoney(left * between(r, 0.42, 0.55));
      left -= part;
      const daysLate = Math.max(-12, late - b * intBetween(r, 7, 11));
      bills.push({ no: `INV-${2280 + i * 17 + b * 5}`, date: addDays(today, -(30 + daysLate)), amount: part, daysLate });
    }
    const kind = kinds[i % kinds.length] as string;
    return {
      id: `c${i}`,
      name: `${stems[i] ?? "Shree"} ${kind}`,
      contact: pick(r, CONTACTS),
      phone: `98${intBetween(r, 100, 999)} ${intBetween(r, 10000, 99999)}`.replace(/(\d{5}) (\d{5})/, "$1 $2"),
      grade,
      outstanding: amount,
      bills,
      avgDelay: grade === "A" ? intBetween(r, 1, 5) : grade === "B" ? intBetween(r, 6, 12) : grade === "C" ? intBetween(r, 18, 26) : intBetween(r, 30, 45),
      payDay: 30 + (grade === "A" ? 2 : grade === "B" ? 9 : grade === "C" ? 25 : 40),
      sales12m: roundMoney(annual * between(r, 0.012, 0.035) * (w + 0.4)),
      lastBuyDays: i === 1 || i === 5 ? intBetween(r, 34, 48) : intBetween(r, 2, 18),
      promisesKept: grade === "A" ? 5 : grade === "B" ? 4 : grade === "C" ? 3 : 1,
      promisesMade: grade === "A" ? 5 : grade === "B" ? 5 : 5,
      since: today.getFullYear() - intBetween(r, 2, 9),
      area: "",
      rep: "",
    };
  });

  /* --- suppliers -------------------------------------------------------- */
  const suppliers = pack.suppliers.map((s, i) => ({
    ...s,
    onTime: [96, 98, 89, 71][i] ?? 90,
    delta: [-0.012, 0.004, -0.004, -0.017][i] ?? 0,
    days: [4, 3, 5, 8][i] ?? 5,
  }));

  /* --- headline numbers -------------------------------------------------- */
  const salesYesterday = roundMoney(perDaySales * between(r, 1.02, 1.14));
  const stockValue = roundMoney(annual * between(r, 0.055, 0.07));
  const idleValue = roundMoney(stockValue * between(r, 0.1, 0.15));
  const payables30 = roundMoney(annual * between(r, 0.075, 0.09));
  const payables7 = roundMoney(payables30 * between(r, 0.22, 0.28));
  const dayOfMonth = Math.max(1, today.getDate());
  const salesMtd = roundMoney(perDaySales * dayOfMonth * 1.15);

  const weekIn = (annual / 52) * 0.62;
  const cash = [1.18, 0.98, 0.74, 1.12].map((f, i) => ({
    label: `Wk ${i + 1}`,
    inflow: roundMoney(weekIn * f),
    outflow: roundMoney(weekIn * [0.97, 1.02, 1.12, 0.93][i]! ),
  }));
  // Week 3 always runs short: a big supplier payment lands before collections do.
  cash[2]!.outflow = roundMoney(cash[2]!.inflow + weekIn * 0.09 + (cash[0]!.inflow - cash[0]!.outflow) + (cash[1]!.inflow - cash[1]!.outflow));

  const m0 = between(r, 5.0, 5.6);
  const margins = [-4, -3, -2, -1, 0].map((o, i) => ({
    label: monthName(o, today),
    value: Math.round((m0 - [0, 0.25, 0.45, 0.4, 0.8][i]!) * 10) / 10,
  }));

  const sales7 = [-6, -5, -4, -3, -2, -1, 0].map((o, i) => {
    const d = addDays(today, o);
    const label = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()] as string;
    const sunday = d.getDay() === 0;
    const value = sunday ? 0 : roundMoney(perDaySales * between(r, 0.82, 1.18) * (i === 5 ? 1.1 : 1));
    return { label, value };
  });

  const team = shuffle(r, TEAM);

  /* --- the long tail of customers --------------------------------------
     A second generator, so adding these leaves every number above exactly
     as it was. The rest of the overdue total is spread over the remaining
     late payers; everyone else has bills that are not yet due. */
  const r2 = makeRng(seedFrom(`${biz.company}|${biz.industry}|${biz.city}|tail`));
  const reps = [team[0] as string, team[1] as string];
  const used = new Set(customers.map((c) => c.name));
  const moreStems = shuffle(r2, MORE_STEMS);
  const extra = CUSTOMER_COUNT - customers.length;
  const lateLeft = Math.max(0, overdueCount - customers.length);
  const overdueSoFar = customers.reduce((a, c) => a + c.bills.filter((b) => b.daysLate > 0).reduce((x, b) => x + b.amount, 0), 0);
  const overdueRest = Math.max(base * lateLeft * 0.6, overdue - overdueSoFar);
  const lateWeights = Array.from({ length: lateLeft }, () => between(r2, 0.6, 1.4));
  const lateSum = lateWeights.reduce((a, b) => a + b, 0) || 1;
  const currentRest = (receivable - overdue) * 0.55;
  const currentEach = currentRest / Math.max(1, extra - lateLeft);
  for (let i = 0; i < extra; i++) {
    let name = "";
    for (let k = 0; k < 6 && (!name || used.has(name)); k++) name = `${moreStems[(i + k * 7) % moreStems.length]} ${pick(r2, pack.customerKinds)}`;
    if (used.has(name)) name = `${name} ${i + 2}`;
    used.add(name);
    const late = i < lateLeft;
    const grade: Grade = late ? (pick(r2, ["B", "C", "B", "C", "D"]) as Grade) : (pick(r2, ["A", "A", "B", "A", "B"]) as Grade);
    const amount = roundMoney(late ? (overdueRest * (lateWeights[i] as number)) / lateSum : currentEach * between(r2, 0.4, 1.6));
    const nBills = amount > base * 0.8 ? 2 : 1;
    const bills: Bill[] = [];
    let left = amount;
    const firstLate = late ? (grade === "D" ? intBetween(r2, 25, 50) : grade === "C" ? intBetween(r2, 10, 24) : intBetween(r2, 1, 9)) : -intBetween(r2, 2, 25);
    for (let b = 0; b < nBills; b++) {
      const part = b === nBills - 1 ? left : roundMoney(left * between(r2, 0.45, 0.6));
      left -= part;
      const daysLate = firstLate - b * intBetween(r2, 6, 12);
      bills.push({ no: `INV-${2460 + i * 13 + b * 4}`, date: addDays(today, -(30 + daysLate)), amount: part, daysLate });
    }
    const avgDelay = grade === "A" ? intBetween(r2, 1, 5) : grade === "B" ? intBetween(r2, 6, 12) : grade === "C" ? intBetween(r2, 18, 26) : intBetween(r2, 30, 45);
    customers.push({
      id: `c${customers.length}`,
      name,
      contact: pick(r2, CONTACTS),
      phone: `9${intBetween(r2, 7000, 9999)} ${intBetween(r2, 10000, 99999)}`,
      grade,
      outstanding: amount,
      bills,
      avgDelay,
      payDay: 30 + (grade === "A" ? 2 : grade === "B" ? 9 : grade === "C" ? 25 : 40),
      // What they owe is roughly what they buy in the days they take to pay,
      // so a year's sales follow from it.
      sales12m: roundMoney(Math.max(annual * 0.004, (amount * 365) / (30 + avgDelay)) * between(r2, 0.85, 1.2)),
      lastBuyDays: i % 11 === 4 ? intBetween(r2, 32, 70) : intBetween(r2, 1, 26),
      promisesKept: grade === "A" ? 4 : grade === "B" ? 3 : grade === "C" ? 2 : 1,
      promisesMade: grade === "A" ? 4 : 4,
      since: today.getFullYear() - intBetween(r2, 1, 12),
      area: "",
      rep: "",
    });
  }
  for (const c of customers) {
    c.area = pick(r2, AREAS);
    c.rep = pick(r2, reps);
  }

  // The headline overdue figures are what the bills actually add up to, so
  // the brief, the desk and every list agree.
  const lateBills = customers.flatMap((c) => c.bills.filter((x) => x.daysLate > 0));
  const overdueReal = roundMoney(lateBills.reduce((a, x) => a + x.amount, 0));
  const overdueCountReal = customers.filter((c) => c.bills.some((x) => x.daysLate > 0)).length;

  return {
    biz,
    pack,
    firstName: firstNameOf(biz.owner),
    products,
    customers,
    suppliers,
    team: { sales: [team[0] as string, team[1] as string], accounts: team[2] as string, purchase: team[3] as string },
    limits: { marginFloor: 3, maxDiscount: 1.5, poLimit: roundMoney(Math.max(5e5, annual / 400)) },
    kpi: {
      salesYesterday,
      vsAverage: Math.round(between(r, 4, 12)),
      salesMtd,
      mtdChange: Math.round(between(r, 3, 9)),
      receivable,
      overdue: overdueReal,
      overdueCount: overdueCountReal,
      dso,
      stockValue,
      idleValue,
      payables7,
      payables30,
      payablesCount: intBetween(r, 6, 12),
      inThisWeek: cash[0]!.inflow,
    },
    cash,
    margins,
    sales7,
    today,
  };
}

/** Margin of a sale at `rate` for a product, in percent. */
export function marginAt(p: Product, rate: number): number {
  return ((rate - p.cost) / rate) * 100;
}
