/* ---------------------------------------------------------------------------
   The public marketing frame: a sticky maroon nav and a three-column footer,
   wrapping every marketing page. Everything is scoped under `.mk`.
   --------------------------------------------------------------------------- */

import { useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { ThemeToggle } from "./lib";
import "./marketing.css";

const NAV = [
  { to: "/product", label: "Product" },
  { to: "/pricing", label: "Pricing" },
  { to: "/about", label: "About" },
  { to: "/contact", label: "Contact" },
];

function Brand({ onFoot = false }: { onFoot?: boolean }) {
  return (
    <Link to="/" className="brand" aria-label="Oprisa home" style={onFoot ? { color: "var(--ink)" } : undefined}>
      Oprisa<span className="dot">.</span>
    </Link>
  );
}

export default function MarketingLayout() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();

  return (
    <div className="mk">
      <div className="mk-nav-outer">
        <div className="wrap mk-nav">
          <Brand />
          <nav className="mk-links" aria-label="Primary">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} className={({ isActive }) => `mk-link${isActive ? " active" : ""}`}>
                {n.label}
              </NavLink>
            ))}
            <Link to="/sign-in" className="mk-link">
              Sign in
            </Link>
            <Link to="/contact" className="btn btn-go" style={{ marginLeft: 6 }}>
              Request access
            </Link>
          </nav>
          <button
            className="mk-burger"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
              {open ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
            </svg>
          </button>
        </div>
        {open && (
          <div className="mk-mobile">
            {NAV.map((n) => (
              <Link key={n.to} to={n.to} onClick={() => setOpen(false)}>
                {n.label}
              </Link>
            ))}
            <Link to="/sign-in" onClick={() => setOpen(false)}>
              Sign in
            </Link>
            <Link to="/contact" onClick={() => setOpen(false)}>
              Request access →
            </Link>
          </div>
        )}
      </div>

      {/* key forces a fresh mount per route so animations re-run */}
      <main key={loc.pathname}>
        <Outlet />
      </main>

      <footer className="mk-foot">
        <div className="wrap mk-foot-grid">
          <div>
            <Brand onFoot />
            <p>
              The AI that runs the back office of a steel distributor — sales, collections, stock and cash flow,
              reported every morning on WhatsApp.
            </p>
          </div>
          <div>
            <h4>Product</h4>
            <ul>
              <li>
                <Link to="/product">How it works</Link>
              </li>
              <li>
                <Link to="/pricing">Pricing</Link>
              </li>
              <li>
                <Link to="/sign-in">Sign in</Link>
              </li>
            </ul>
          </div>
          <div>
            <h4>Company</h4>
            <ul>
              <li>
                <Link to="/about">About &amp; roadmap</Link>
              </li>
              <li>
                <Link to="/contact">Request access</Link>
              </li>
              <li>
                <a href="mailto:hello@opriza.com">hello@opriza.com</a>
              </li>
            </ul>
          </div>
        </div>
        <div className="wrap mk-foot-bar">
          <span>© {new Date().getFullYear()} Oprisa · Built for ₹100–500 Cr distributors</span>
          <span style={{ display: "flex", alignItems: "center", gap: 14 }}>
            Quotation Copilot is live today
            <ThemeToggle />
          </span>
        </div>
      </footer>
    </div>
  );
}
