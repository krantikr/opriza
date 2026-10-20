import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";

import { api } from "../api/client";
import "../demo/demo.css";
import { useAuth } from "../lib/auth";
import Desk from "./Desk";
import Phone from "./Phone";
import "./product.css";
import { VersionContext, type Me } from "./data";

/* ---------------------------------------------------------------------------
   /app - the Oprisa product: the agents' desk on a computer, the chat app on
   a phone. Reads everything from /api/v1/app, which reads the knowledge base
   the agents keep in step with Tally (or with the sample books on a mock
   desk). Lazy-loaded from App.tsx, so the older screens don't carry it.
   --------------------------------------------------------------------------- */

const DESK_MEDIA = "(min-width: 1100px)";

function useMedia(q: string) {
  const [hit, setHit] = useState(() => typeof window !== "undefined" && window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const on = () => setHit(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [q]);
  return hit;
}

function Full({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="odemo">
      <div className="op-full">
        <div className="box">
          <h1>{title}</h1>
          {children}
        </div>
      </div>
    </div>
  );
}

export default function ProductApp() {
  const { user, loading } = useAuth();
  const [me, setMe] = useState<Me | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((v) => v + 1), []);
  const versionValue = useMemo(() => ({ version, bump }), [version, bump]);
  const wide = useMedia(DESK_MEDIA);

  useEffect(() => {
    if (!user) return;
    api.get<Me>("/app/me").then(setMe).catch((e: Error) => setErr(e.message));
  }, [user, version]);

  useEffect(() => {
    if (me?.organisation) document.title = `${me.organisation.name} · Oprisa`;
  }, [me?.organisation]);

  if (loading) return <Full title="Opening Oprisa…" />;
  if (!user) return <Navigate to="/sign-in" replace />;
  if (user.is_super_admin) return <Navigate to="/admin" replace />;
  if (err && !me) {
    return (
      <Full title="Couldn't open your desk">
        <p>{err}</p>
        <button type="button" className="btn btn-go btn-sm" onClick={() => { setErr(null); bump(); }}>Try again</button>
      </Full>
    );
  }
  if (!me) return <Full title="Opening Oprisa…" />;
  if (!me.business) {
    return (
      <Full title="The agents aren't set up for this desk yet">
        <p>Oprisa's agents run on a knowledge base built from your Tally books. Once your Tally is connected (or sample books are loaded), they start here.</p>
        <Link className="btn btn-line btn-sm" to="/">Go to your desk</Link>
      </Full>
    );
  }

  return (
    <VersionContext.Provider value={versionValue}>
      <div className="odemo">
        {wide ? (
          <div className="app app-desk">
            <Routes>
              <Route path=":page?" element={<Desk me={me} />} />
            </Routes>
          </div>
        ) : (
          <Phone me={me} />
        )}
      </div>
    </VersionContext.Provider>
  );
}
