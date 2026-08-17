import { PageHeader } from "@/components/page-header";
import { listDecisions } from "@/lib/api/decisions";
import Link from "next/link";

export default async function HistoryPage() {
  const decisions = await listDecisions();

  return (
    <section>
      <PageHeader eyebrow="History" title="Your Decisions" subtitle="Recent runs" />

      <article className="surface-card p-4">
        <div className="grid gap-2">
          {decisions.length === 0 && (
            <div className="surface-panel p-6 text-center">
              <p className="text-sm font-medium text-brand-text">No saved decisions yet.</p>
              <Link href="/decision/conversation" className="mt-2 inline-block text-sm font-medium text-brand-primary hover:underline">
                Start your first decision
              </Link>
            </div>
          )}
          {decisions.map((decision) => (
            <Link
              key={decision.id}
              href={`/decision/${decision.id}`}
              className="surface-panel flex flex-col gap-2 p-3 md:flex-row md:items-center md:justify-between"
            >
              <div>
                <p className="text-[11px] uppercase tracking-[0.15em] text-brand-muted">{decision.status}</p>
                <h3 className="mt-0.5 text-sm font-semibold text-brand-text">{decision.title}</h3>
              </div>
              <div className="flex items-center gap-2 text-xs text-brand-muted">
                <span>{new Date(decision.updated_at).toLocaleDateString()}</span>
              </div>
            </Link>
          ))}
        </div>
      </article>
    </section>
  );
}
