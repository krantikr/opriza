/* ---------------------------------------------------------------------------
   Contact — request a design-partner slot. Posts to the public
   `/api/v1/leads` endpoint, which stores the request in the database. No
   account or token needed; the endpoint is unauthenticated by design.
   --------------------------------------------------------------------------- */

import { useState } from "react";

import { Reveal, useSeo } from "./lib";

const INBOX = "hello@opriza.com";

type Status = "idle" | "sending" | "done" | "error";

export default function Contact() {
  useSeo({
    title: "Request access",
    description:
      "Request a design-partner slot for Oprisa. Connect Tally, WhatsApp and Gmail, and put your quoting on autopilot while you keep the final word.",
    path: "/contact",
  });

  const [form, setForm] = useState({ name: "", company: "", email: "", phone: "", volume: "", note: "" });
  const [website, setWebsite] = useState(""); // honeypot
  const [status, setStatus] = useState<Status>("idle");

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus("sending");
    try {
      const res = await fetch("/api/v1/leads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          company: form.company,
          email: form.email,
          phone: form.phone,
          monthly_enquiries: form.volume || null,
          note: form.note || null,
          website: website || null,
        }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setStatus("done");
    } catch {
      setStatus("error");
    }
  };

  return (
    <>
      <header className="page-head">
        <div className="wrap">
          <Reveal>
            <p className="eyebrow" style={{ color: "var(--saffron)" }}>
              Early access
            </p>
            <h1 className="page-title">Request a design-partner slot.</h1>
            <p className="page-sub">
              Tell us about your desk. We'll set up a short call, connect your data, and show you the morning brief on
              your own numbers — usually within the week.
            </p>
          </Reveal>
        </div>
      </header>

      <section>
        <div className="wrap contact-grid">
          <Reveal className="contact-form-wrap">
            {status === "done" ? (
              <div className="sent">
                <div className="sent-mark">
                  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6}>
                    <path d="M4 12.5l5 5 11-12" />
                  </svg>
                </div>
                <h3>Request received.</h3>
                <p>
                  Thanks, {form.name.split(" ")[0] || "there"} — it's in. We'll be in touch within a day or two to set up
                  your call. Anything urgent, write to us directly:
                </p>
                <a className="copy-mail" href={`mailto:${INBOX}`}>
                  {INBOX}
                </a>
              </div>
            ) : (
              <form className="contact-form" onSubmit={submit}>
                <div className="field">
                  <label htmlFor="c-name">Your name</label>
                  <input id="c-name" value={form.name} onChange={set("name")} required autoComplete="name" />
                </div>
                <div className="field">
                  <label htmlFor="c-company">Company</label>
                  <input id="c-company" value={form.company} onChange={set("company")} required autoComplete="organization" />
                </div>
                <div className="field">
                  <label htmlFor="c-email">Email</label>
                  <input id="c-email" type="email" value={form.email} onChange={set("email")} required autoComplete="email" />
                </div>
                <div className="field">
                  <label htmlFor="c-phone">Phone / WhatsApp</label>
                  <input
                    id="c-phone"
                    type="tel"
                    value={form.phone}
                    onChange={set("phone")}
                    required
                    autoComplete="tel"
                    inputMode="tel"
                    placeholder="+91 98765 43210"
                  />
                </div>
                <div className="field">
                  <label htmlFor="c-vol">Enquiries a month (roughly)</label>
                  <input id="c-vol" value={form.volume} onChange={set("volume")} placeholder="e.g. 200" inputMode="numeric" />
                </div>
                <div className="field">
                  <label htmlFor="c-note">Anything we should know?</label>
                  <textarea
                    id="c-note"
                    value={form.note}
                    onChange={set("note")}
                    rows={4}
                    placeholder="What's leaking — slow quotes, late payments, dead stock?"
                  />
                </div>
                {/* Honeypot: hidden from people, tempting to bots. */}
                <div aria-hidden="true" style={{ position: "absolute", left: "-9999px", width: 1, height: 1, overflow: "hidden" }}>
                  <label htmlFor="c-website">Website</label>
                  <input id="c-website" tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
                </div>
                {status === "error" && (
                  <p className="form-err" role="alert">
                    Something went wrong sending that. Try again, or email us at{" "}
                    <a href={`mailto:${INBOX}`}>{INBOX}</a>.
                  </p>
                )}
                <button className="btn btn-go" type="submit" disabled={status === "sending"} style={{ width: "100%", justifyContent: "center" }}>
                  {status === "sending" ? "Sending…" : "Request access"}
                </button>
                <p className="form-fine">We reply within a day or two. No spam, ever.</p>
              </form>
            )}
          </Reveal>

          <Reveal delay={120} className="contact-aside">
            <h3>What happens next</h3>
            <ol className="steps-list">
              <li>
                <span>1</span>A 20-minute call to understand your enquiry flow and where orders and cash are leaking.
              </li>
              <li>
                <span>2</span>We connect Tally, Gmail and WhatsApp — about two minutes, no migration.
              </li>
              <li>
                <span>3</span>You see the Quotation Copilot and the morning brief running on your own data.
              </li>
            </ol>
            <div className="contact-mail-card">
              <h4>Prefer email?</h4>
              <a href={`mailto:${INBOX}`}>{INBOX}</a>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
