import { Empty, PageHead, Panel } from "../../demo/desk/ui";
import { CashBars } from "../bits";
import { useDesk } from "../ctx";
import { day, money, stamp, useData, type Cash as Data } from "../data";

export default function Cash() {
  const ctx = useDesk();
  const { data } = useData<Data>("/app/cash", 60000);
  if (!data) return <Empty title="Loading…" />;
  const short = data.weeks.find((w) => w.closing < data.floor);
  return (
    <>
      <PageHead title="Cash" sub={<>Bank today <b>{money(data.bank)}</b>{data.bank_at ? ` (from Tally, ${stamp(data.bank_at)})` : ""}. {short ? <>Goes short in the <b>week of {day(short.week_start)}</b>.</> : "Fine for the next four weeks."}</>}>
        <button type="button" className="btn btn-line btn-sm" onClick={() => ctx.chat("cash")}>Open the Cash agent</button>
      </PageHead>
      <Panel title="Next four weeks" sub="Open bills by each customer's payment habit, supplier dues, salaries, rent and GST">
        <CashBars weeks={data.weeks} />
      </Panel>
      <div className="dk-grid2">
        <Panel title="Week by week" pad={false}>
          <table className="dk-table">
            <thead><tr><th>Week</th><th className="r">Opening</th><th className="r">In</th><th className="r">Out</th><th className="r">Closing</th></tr></thead>
            <tbody>
              {data.weeks.map((w, i) => (
                <tr key={w.week_start} className={w.closing < data.floor ? "short" : ""}>
                  <td>Week {i + 1} · {day(w.week_start)}</td>
                  <td className="r num">{money(w.opening)}</td><td className="r num pos">{money(w.inflow)}</td>
                  <td className="r num neg">{money(w.outflow)}</td><td className={`r num ${w.closing < 0 ? "bad" : ""}`}><b>{money(w.closing)}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
          {short && (
            <div className="dk-fine">
              Biggest going out that week: {short.out_top.slice(0, 3).map((x) => `${x.name} ${money(x.amount)}`).join(", ")}.
              Coming in: {short.in_top.slice(0, 3).map((x) => `${x.name} ${money(x.amount)}`).join(", ")}.
            </div>
          )}
        </Panel>
        <Panel title="Supplier bills, next 4 weeks" pad={false}>
          <table className="dk-table compact">
            <thead><tr><th>Supplier</th><th>Bill</th><th>Due</th><th className="r">Amount</th></tr></thead>
            <tbody>
              {data.payables.map((b) => (
                <tr key={b.id}><td>{b.party}</td><td className="muted">{b.ref}</td><td>{day(b.due)}</td><td className="r num">{money(b.amount)}</td></tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </>
  );
}
