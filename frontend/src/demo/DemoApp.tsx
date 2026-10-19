import { useEffect, useState, type ReactElement } from "react";
import "./demo.css";
import type { Business } from "./engine/types";
import Demo from "./screens/Demo";
import Details from "./screens/Details";
import Problems from "./screens/Problems";

/* ---------------------------------------------------------------------------
   The /demo page.

   A prospect picks their problems, tells us about their business, and lands
   in a working copy of Oprisa filled with mock data built from those answers.
   Public, no session, no API calls: everything runs in the browser, and
   nothing they type leaves it.
   --------------------------------------------------------------------------- */

type Stage = "problems" | "details" | "demo";

const KEY = "oprisa-demo-setup-v1";

const EMPTY: Business = {
  company: "",
  owner: "",
  city: "",
  industry: "steel",
  revenue: "100-250",
  team: "10–25",
  tally: "TallyPrime",
  language: "English",
  problems: [],
};

/** Remembers where the visitor got to, so a refresh doesn't throw away what
 *  they typed. Storage can be missing or blocked; the demo works without it. */
function load(): { stage: Stage; biz: Business } {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const v = JSON.parse(raw) as { stage: Stage; biz: Business };
      if (v?.biz && v.stage) return { stage: v.stage, biz: { ...EMPTY, ...v.biz } };
    }
  } catch {
    /* ignore */
  }
  return { stage: "problems", biz: EMPTY };
}

export default function DemoApp() {
  const [{ stage, biz }, setAll] = useState(load);
  const [live, setLive] = useState<Business | null>(stage === "demo" ? biz : null);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ stage, biz }));
    } catch {
      /* ignore */
    }
  }, [stage, biz]);

  useEffect(() => {
    window.scrollTo(0, 0);
    document.title = stage === "demo" ? `${biz.company || "Your business"} · Oprisa demo` : "Try Oprisa — live demo";
  }, [stage, biz.company]);

  const go = (s: Stage) => setAll((v) => ({ ...v, stage: s }));
  const setBiz = (b: Business) => setAll((v) => ({ ...v, biz: b }));

  let screen: ReactElement;
  if (stage === "problems") {
    screen = <Problems selected={biz.problems} onChange={(problems) => setBiz({ ...biz, problems })} onNext={() => go("details")} />;
  } else if (stage === "details" || !live) {
    screen = (
      <Details
        biz={biz}
        onChange={setBiz}
        onBack={() => go("problems")}
        onStart={() => {
          setLive({ ...biz, company: biz.company.trim(), owner: biz.owner.trim(), city: biz.city.trim() });
          go("demo");
        }}
      />
    );
  } else {
    screen = <Demo biz={live} onEdit={() => go("details")} />;
  }

  return <div className="odemo">{screen}</div>;
}
