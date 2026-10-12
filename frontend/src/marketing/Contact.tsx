/* ---------------------------------------------------------------------------
   Contact — request a design-partner slot. The form opens the visitor's own
   email client pre-filled (no backend endpoint for leads yet), so we never
   claim a message was sent when it wasn't.
   --------------------------------------------------------------------------- */

import { useState } from "react";

import { Reveal, useSeo } from "./lib";

const INBOX = "hello@opriza.com";

export default function Contact() {
  useSeo({
    title: "Request access",
    description:
      "Request a design-partner slot for Oprisa. Connect Tally, WhatsApp and Gmail, and put your quoting on autopilot while you keep the final word.",
    path: "/contact",
  });

  const [form, setForm] = useState({ name: "", company: "", email: "", volume: "", note: "" });
  const [opened, setOpened] = useState(false);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const subject = `Design-partner request — ${form.company || form.name || "Oprisa"}`;
    const body = [
      `Name: ${form.name}`,
      `Company: ${form.company}`,
      `Email: ${form.email}`,
      `Monthly enquiries: ${form.volume || "—"}`,
      "",
      form.note,
    ].join("\n");
    const href = `mailto:${INBOX}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    // Opening the mail client is best-effort; we only tell the visitor what we
    // actually did — prepared a draft — and give them the address to copy.
    window.location.href = href;
    setOpened(true);
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
            {opened ? (
              <div className="sent">
                <div className="sent-mark">
                  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6}>
                    <path d="M4 12.5l5 5 11-12" />
                  </svg>
                </div>
                <h3>Your email is drafted.</h3>
                <p>
                  We opened your mail app with everything filled in — just hit send. If nothing opened, write to us
                  directly:
                </p>
                <a className="copy-mail" href={`mailto:${INBOX}`}>
                  {INBOX}
                </a>
                <button className="btn btn-ghost" type="button" onClick={() => setOpened(false)} style={{ marginTop: 18 }}>
                  Edit the details
                </button>
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
                  <label htmlFor="c-vol">Enquiries a month (roughly)</label>
                  <input id="c-vol" value={form.volume} onChange={set("volume")} placeholder="e.g. 200" inputMode="numeric" />
                </div>
                <div className="field">
                  <label htmlFor="c-note">Anything we should know?</label>
                  <textarea id="c-note" value={form.note} onChange={set("note")} rows={4} placeholder="What's leaking — slow quotes, late payments, dead stock?" />
                </div>
                <button className="btn btn-go" type="submit" style={{ width: "100%", justifyContent: "center" }}>
                  Prepare my request
                </button>
                <p className="form-fine">Opens your mail app with the details filled in. We reply within a day or two.</p>
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
