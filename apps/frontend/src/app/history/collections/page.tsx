import { PageHeader } from "@/components/page-header";

const collections = [
  { name: "Career Decisions", decisions: 14, trend: "+8% confidence" },
  { name: "Financial Tradeoffs", decisions: 9, trend: "Stable" },
  { name: "Lifestyle Moves", decisions: 7, trend: "+5% confidence" },
];

export default function CollectionsPage() {
  return (
    <section>
      <PageHeader eyebrow="Collections" title="Decision Collections" subtitle="Grouped by theme" />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {collections.map((collection) => (
          <article key={collection.name} className="surface-card p-5">
            <h3 className="text-base font-semibold text-brand-text">{collection.name}</h3>
            <p className="mt-1 text-xs text-brand-muted">{collection.decisions} decisions</p>
            <p className="mt-3 inline-flex rounded-lg bg-brand-soft px-3 py-1 text-xs text-brand-text">{collection.trend}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
