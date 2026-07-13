import { PageHeader } from "@/components/page-header";

export default function RecommendationReportPage() {
  return (
    <section>
      <PageHeader eyebrow="Report" title="Recommendation" subtitle="A clear pick, the reasons behind it, and the checks that would change the answer." />

      <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
        <article className="surface-card p-5">
          <p className="text-[11px] uppercase tracking-[0.18em] text-brand-muted">Top Recommendation</p>
          <h3 className="mt-2 text-2xl font-semibold leading-tight text-brand-text md:text-3xl">
            Accept the startup role with a 6-month review checkpoint.
          </h3>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-brand-muted">
            The learning upside is strong enough to justify the moderate income risk if compensation terms and runway are confirmed before signing.
          </p>

          <div className="mt-5 grid gap-2 sm:grid-cols-3">
            <div className="surface-panel p-3">
              <p className="text-[11px] uppercase tracking-[0.15em] text-brand-muted">Confidence</p>
              <p className="mt-1 text-2xl font-semibold text-brand-primary">0.78</p>
            </div>
            <div className="surface-panel p-3">
              <p className="text-[11px] uppercase tracking-[0.15em] text-brand-muted">Risk</p>
              <p className="mt-1 text-base font-semibold text-brand-warning">Moderate</p>
            </div>
            <div className="surface-panel p-3">
              <p className="text-[11px] uppercase tracking-[0.15em] text-brand-muted">Review</p>
              <p className="mt-1 text-base font-semibold text-brand-text">6 months</p>
            </div>
          </div>
        </article>

        <article className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Checks</h3>
          <ul className="mt-3 grid gap-2 text-sm text-brand-muted">
            {["Runway above 18 months", "Comp terms confirmed", "Mentorship path clear"].map((check) => (
              <li key={check} className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-brand-success" />
                <span>{check}</span>
              </li>
            ))}
          </ul>
          <h4 className="mt-4 text-[11px] font-semibold uppercase tracking-[0.15em] text-brand-muted">Alternate</h4>
          <p className="mt-1 text-sm leading-6 text-brand-text">
            Stay in the current role if the startup cannot verify runway or if the final package drops below your salary floor.
          </p>
        </article>
      </div>
    </section>
  );
}
