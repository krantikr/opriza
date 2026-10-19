import { useState } from "react";
import { cashAskEarly, cashDelay, delayAmount, earlyPayers } from "../engine/desk";
import { money } from "../lib/format";
import type { Ctx } from "./ctx";
import { CashBars } from "./Home";
import { IArrow, IChat, ISend } from "./icons";
import { chaseOrder } from "./select";
import { GradeTag, PageHead, Panel, Toggle } from "./ui";

export default function Cash({ ctx }: { ctx: Ctx }) {
  const s = ctx.s;
  const w = s.world;
  const [late, setLate] = useState(false);
  const fix = s.desk.cashFix;
  const big = chaseOrder(w)[0]!;
  const shift = late ? Math.round((big.outstanding * 0.6) / 1e5) * 1e5 : 0;
  const delay = fix.delayed ? delayAmount(s) : 0;
  const weeks = w.cash.map((wk, i) => ({
    ...wk,
    inflow: wk.inflow + (i === 1 ? -shift : 0) + (i === 3 ? shift : 0) + (i === 2 ? fix.early : 0),
    outflow: wk.outflow - (i === 2 ? delay : 0) + (i === 3 ? delay : 0),
  }));
  const net = weeks.map((wk) => wk.inflow - wk.outflow);
  const low = Math.min(...net);
  const lowIdx = net.indexOf(low);
  const totalIn = weeks.reduce((a, x) => a + x.inflow, 0);
  const totalOut = weeks.reduce((a, x) => a + x.outflow, 0);
  const payers = earlyPayers(s);
  const earlySum = payers.reduce((a, c) => a + c.outstanding, 0);
  const asked = s.desk.log.some((l) => l.agent === "cash" && l.text.startsWith("Asked") && l.text.includes("pay this week"));
  const delayAsked = s.desk.log.some((l) => l.agent === "cash" && l.text.includes("by 5 days"));

  return (
    <>
      <PageHead title="Cash" sub="Will we run short, and when? From bills, payment habits and supplier dues in Tally." />

      <div className="dk-stats">
        <div><span>Coming in, 4 weeks</span><b>{money(totalIn)}</b><small>From open bills and how each customer pays</small></div>
        <div><span>Going out, 4 weeks</span><b>{money(totalOut)}</b><small>Suppliers, salaries, GST, rent</small></div>
        <div><span>Shortest week</span><b className={low < 0 ? "neg" : "pos"}>{money(low)}</b><small>{weeks[lowIdx]!.label.replace("Wk", "Week")}{low < 0 ? " · fixes below" : " · covered"}</small></div>
        <div><span>To suppliers, 7 days</span><b>{money(w.kpi.payables7)}</b><small>{w.kpi.payablesCount} suppliers this month</small></div>
      </div>

      <div className="dk-grid2 wide-l">
        <Panel title="Next 4 weeks" sub={low < 0 ? `${weeks[lowIdx]!.label.replace("Wk", "Week")} is ${money(-low)} short` : "Every week is covered"}>
          <CashBars s={s} shift={shift} early={fix.early} delay={delay} />
          <div className="dk-whatif">
            <Toggle on={late} onChange={setLate} label="What if the biggest customer pays late" />
            <span>
              <b>What if {big.name} pays 15 days late?</b>
              <small>Moves {money(Math.round((big.outstanding * 0.6) / 1e5) * 1e5)} from week 2 to week 4</small>
            </span>
          </div>
        </Panel>

        <Panel title="Close the gap" sub="Each fix shows what it does to the short week">
          <div className="dk-fixes">
            <div className="dk-fix">
              <div>
                <b>Ask 4 good payers to pay this week</b>
                <small>Up to {money(earlySum)} · they pay on time and have bills due soon</small>
                <ul className="dk-mini">
                  {payers.map((c) => (
                    <li key={c.id}><GradeTag g={c.grade} /> {c.name} · {money(c.outstanding)}</li>
                  ))}
                </ul>
              </div>
              <button type="button" className="btn btn-go btn-sm" disabled={asked} onClick={() => ctx.run(cashAskEarly(ctx.s))}>
                <ISend /> {fix.early ? `+${money(fix.early)} agreed` : asked ? "Asked" : "Ask them"}
              </button>
            </div>
            <div className="dk-fix">
              <div>
                <b>Move {w.suppliers[0]!.name}'s payment by 5 days</b>
                <small>Shifts {money(delayAmount(s))} from week 3 to week 4 · they agreed last time</small>
              </div>
              <button type="button" className="btn btn-line btn-sm" disabled={delayAsked} onClick={() => ctx.run(cashDelay(ctx.s))}>
                {fix.delayed ? "Moved ✓" : delayAsked ? "Asked" : "Ask supplier"}
              </button>
            </div>
            <div className="dk-fix">
              <div>
                <b>Work today's call list</b>
                <small>{money(w.kpi.overdue)} overdue · promises land in the forecast as they come</small>
              </div>
              <button type="button" className="btn btn-line btn-sm" onClick={() => ctx.go("collect")}>Open Collections <IArrow /></button>
            </div>
          </div>
          <button type="button" className="dk-link" onClick={() => ctx.chat("cash", "Cash position today")}><IChat size={16} /> Ask the Cash agent</button>
        </Panel>
      </div>

      <Panel title="Week by week" pad={false}>
        <table className="dk-table">
          <thead><tr><th>Week</th><th className="r">Coming in</th><th className="r">Going out</th><th className="r">Net</th><th>What drives it</th></tr></thead>
          <tbody>
            {weeks.map((wk, i) => (
              <tr key={wk.label} className={net[i]! < 0 ? "short" : ""}>
                <td><b>{wk.label.replace("Wk", "Week")}</b></td>
                <td className="r num">{money(wk.inflow)}</td>
                <td className="r num">{money(wk.outflow)}</td>
                <td className={`r num ${net[i]! < 0 ? "neg" : "pos"}`}>{net[i]! < 0 ? "" : "+"}{money(net[i]!)}</td>
                <td className="muted">
                  {i === 0 && "Bills due from grade A customers; GST payment"}
                  {i === 1 && (late ? `${big.name}'s payment moved out` : "Large customer payments due")}
                  {i === 2 && (fix.delayed || fix.early ? "Supplier payment and salaries — gap being closed" : `${w.suppliers[0]!.name} payment and salaries fall together`)}
                  {i === 3 && "Month-start collections"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
