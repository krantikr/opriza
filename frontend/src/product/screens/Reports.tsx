import { Empty, PageHead, Panel } from "../../demo/desk/ui";
import { Bars, Spark } from "../bits";
import { money, useData, type Reports as Data } from "../data";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function Reports() {
  const { data } = useData<Data>("/app/reports");
  if (!data) return <Empty title="Loading…" />;
  const total = Object.values(data.grades).reduce((a, b) => a + b, 0) || 1;
  const recvNow = data.receivable.at(-1)?.value ?? 0;
  const overNow = data.overdue.at(-1)?.value ?? 0;
  return (
    <>
      <PageHead title="Reports" sub="Straight from the books in Tally, worked out by code. Ask Oprisa for anything that isn't here." />
      <Panel title="Sales by month" sub="Before tax, last 12 months">
        <Bars rows={data.sales_by_month.map((m) => ({ label: MONTHS[Number(m.month.slice(5, 7)) - 1]!, value: m.value }))} highlight={data.sales_by_month.length - 1} />
      </Panel>
      <div className="dk-grid2">
        <Panel title="Owed to you, last 90 days" sub={`${money(recvNow)} now`}>
          <Spark points={data.receivable.map((p) => p.value)} label="Receivable, last 90 days" />
        </Panel>
        <Panel title="Overdue, last 90 days" sub={`${money(overNow)} now`}>
          <Spark points={data.overdue.map((p) => p.value)} tone="var(--bad)" label="Overdue, last 90 days" />
        </Panel>
      </div>
      <div className="dk-grid2">
        <Panel title="Customers by grade" sub="Customers who bought in the last 12 months">
          <div className="op-grades">
            {(["A", "B", "C", "D"] as const).map((g) => (
              <div key={g} className={`g-${g}`}>
                <span className={`dk-grade g-${g}`}>{g}</span>
                <i style={{ width: `${(data.grades[g]! / total) * 100}%` }} />
                <b>{data.grades[g]}</b>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Top customers" sub="Sales in the last 12 months" pad={false}>
          <table className="dk-table compact">
            <tbody>
              {data.top_customers.map((c, i) => (
                <tr key={c.name}><td className="muted">{i + 1}</td><td><b>{c.name}</b></td><td><span className={`dk-grade g-${c.grade}`}>{c.grade}</span></td><td className="r num">{money(c.sales_12m)}</td></tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </>
  );
}
