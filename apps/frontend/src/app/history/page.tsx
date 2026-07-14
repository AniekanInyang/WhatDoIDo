import { PageHeader } from "@/components/page-header";
import { historyItems } from "@/lib/mock-data";

export default function HistoryPage() {
  return (
    <section>
      <PageHeader eyebrow="History" title="Your Decisions" subtitle="Recent runs" />

      <article className="surface-card p-4">
        <div className="grid gap-2">
          {historyItems.map((item) => (
            <div
              key={item.id}
              className="surface-panel flex flex-col gap-2 p-3 md:flex-row md:items-center md:justify-between"
            >
              <div>
                <p className="text-[11px] uppercase tracking-[0.15em] text-brand-muted">{item.id}</p>
                <h3 className="mt-0.5 text-sm font-semibold text-brand-text">{item.title}</h3>
              </div>
              <div className="flex items-center gap-2 text-xs text-brand-muted">
                <span>{item.date}</span>
                <span className="rounded-lg bg-brand-primary/15 px-2.5 py-1 text-brand-text">{item.confidence}</span>
              </div>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}
