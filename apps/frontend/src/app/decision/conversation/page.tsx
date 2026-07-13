import Link from "next/link";
import { PageHeader } from "@/components/page-header";

export default function DecisionConversationPage() {
  return (
    <section className="mx-auto max-w-5xl">
      <PageHeader eyebrow="Conversation" title="New Decision" subtitle="Simple, focused flow" />

      <div className="grid gap-4 lg:grid-cols-[1.45fr_0.75fr]">
        <article className="surface-card p-5">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-[11px] uppercase tracking-[0.18em] text-brand-muted">Conversation</p>
            <div className="flex gap-2">
              <Link
                href="/decision/report"
                className="rounded-lg bg-brand-primary px-3 py-1.5 text-xs font-medium text-white transition hover:bg-brand-hover"
              >
                Report
              </Link>
              <Link
                href="/decision/detail"
                className="rounded-lg border border-brand-border bg-brand-soft px-3 py-1.5 text-xs font-medium text-brand-text transition hover:border-brand-accent"
              >
                Detail
              </Link>
            </div>
          </div>
          <div className="flex min-h-[52vh] items-center justify-center rounded-xl border border-dashed border-brand-border bg-brand-soft/40 p-6 text-center">
            <div>
              <p className="text-sm font-medium text-brand-text">What decision do you need help with today?</p>
              <p className="mt-1 text-xs text-brand-muted">Start typing below to begin a new conversation.</p>
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <input
              className="flex-1 rounded-xl border border-brand-border bg-brand-soft p-3 text-sm"
              placeholder="Type your message"
            />
            <button className="rounded-xl bg-brand-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-hover">
              Send
            </button>
          </div>
        </article>

        <aside className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Snapshot</h3>
          <div className="mt-3 grid gap-2 text-sm text-brand-muted">
            <div className="rounded-lg border border-brand-border bg-brand-soft p-3">
              <p className="font-medium text-brand-text">Goal</p>
              <p>Startup vs current role</p>
            </div>
            <div className="rounded-lg border border-brand-border bg-brand-soft p-3">
              <p className="font-medium text-brand-text">Constraints</p>
              <p>Salary floor, no relocation</p>
            </div>
            <div className="rounded-lg border border-brand-border bg-brand-soft p-3">
              <p className="font-medium text-brand-text">Confidence</p>
              <p className="text-lg font-semibold text-brand-primary">0.68</p>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}
