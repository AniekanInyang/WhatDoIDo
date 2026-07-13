import { PageHeader } from "@/components/page-header";
import { insightStats } from "@/lib/mock-data";

export default function InsightsPage() {
  return (
    <section>
      <PageHeader eyebrow="Insights" title="Decision Insights" subtitle="Signal overview" />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {insightStats.map((stat) => (
          <article key={stat.label} className="surface-card p-5">
            <p className="text-xs text-brand-muted">{stat.label}</p>
            <p className="mt-1 text-2xl font-semibold text-brand-text">{stat.value}</p>
          </article>
        ))}
      </div>

      <article className="surface-card mt-4 p-5">
        <h3 className="text-base font-semibold text-brand-text">This week</h3>
        <p className="mt-1 text-sm text-brand-muted">Confidence up. Biggest misses still come from vague constraints early.</p>
      </article>
    </section>
  );
}
