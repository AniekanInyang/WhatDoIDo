import { PageHeader } from "@/components/page-header";

export default function RecommendationReportPage() {
  return (
    <section>
      <PageHeader eyebrow="Report" title="Recommendation" subtitle="Clear pick, clear tradeoffs." />

      <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
        <article className="surface-card p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-brand-muted">Top Recommendation</p>
          <h3 className="mt-2 text-2xl font-semibold text-brand-text">Accept startup role with 6-month review checkpoint</h3>

          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            <div className="rounded-xl border border-brand-border bg-brand-soft p-3">
              <p className="text-[11px] uppercase tracking-[0.15em] text-brand-muted">Confidence</p>
              <p className="mt-1 text-2xl font-semibold text-brand-primary">0.78</p>
            </div>
            <div className="rounded-xl border border-brand-border bg-brand-soft p-3">
              <p className="text-[11px] uppercase tracking-[0.15em] text-brand-muted">Risk</p>
              <p className="mt-1 text-base font-semibold text-brand-text">Moderate</p>
            </div>
          </div>
        </article>

        <article className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Checks</h3>
          <ul className="mt-3 grid gap-1.5 text-sm text-brand-muted">
            <li>Runway above 18 months</li>
            <li>Comp terms confirmed</li>
            <li>Mentorship path clear</li>
          </ul>
          <h4 className="mt-4 text-[11px] font-semibold uppercase tracking-[0.15em] text-brand-muted">Alternate</h4>
          <p className="mt-1 text-sm text-brand-text">Stay in current role for maximum stability.</p>
        </article>
      </div>
    </section>
  );
}
