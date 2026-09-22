import Link from "next/link";
import { LandingDecisionForm } from "@/components/landing-decision-form";
import { startDecision } from "@/app/decision/conversation/actions";

export default function LandingPage() {
  return (
    <section className="mx-auto grid max-w-6xl gap-5 lg:grid-cols-[1.1fr_0.9fr] lg:items-start">
      <div className="py-3 md:py-10">
        <p className="text-[11px] uppercase tracking-[0.18em] text-brand-muted">Home</p>
        <h2 className="headline mt-3 max-w-3xl text-4xl font-semibold leading-tight text-brand-text md:text-5xl">
          Make the next hard choice feel smaller.
        </h2>
        <p className="mt-4 max-w-2xl text-base leading-7 text-brand-muted">
          Work through the messy tradeoffs, compare realistic options, and leave with a clear recommendation you can revisit.
        </p>
        <div className="mt-6 flex flex-wrap gap-2">
          <Link
            href="/decision/conversation"
            className="rounded-lg bg-brand-primary px-4 py-2.5 text-sm font-medium text-white transition hover:bg-brand-hover"
          >
            Start a Decision
          </Link>
        </div>
      </div>

      <article className="surface-card p-4 md:p-5">
        <div className="flex items-center justify-between gap-3 border-b border-brand-border pb-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.18em] text-brand-muted">New Decision</p>
            <h3 className="mt-1 text-lg font-semibold text-brand-text">Start with one sentence</h3>
          </div>
          <span className="rounded-lg bg-brand-soft px-3 py-1.5 text-xs font-medium text-brand-text">Draft</span>
        </div>

        <LandingDecisionForm action={startDecision} />
      </article>
    </section>
  );
}
