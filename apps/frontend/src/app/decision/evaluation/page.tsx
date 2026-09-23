import { PageHeader } from "@/components/page-header";
import { getDecision } from "@/lib/api/decisions";
import Link from "next/link";
import { redirect } from "next/navigation";

export default async function EvaluationBoardPage({ searchParams }: { searchParams: { id?: string } }) {
  if (!searchParams.id) redirect("/history");
  const decision = await getDecision(searchParams.id);
  const recommendation = decision.recommendation as null | {
    option_assessments?: Array<{ option_id: string; option_title: string; fit: string; strengths: string[]; tradeoffs: string[]; constraint_conflicts: string[] }>;
    key_risks?: Array<{ id?: string; title: string; severity: string; likelihood: string; description: string; mitigation?: string | null }>;
    robustness?: string;
  };
  const assessments = recommendation?.option_assessments ?? [];

  return (
    <section>
      <PageHeader eyebrow="Evaluation" title={decision.title} subtitle="A grounded comparison of every option against the confirmed Decision Brief." />
      {!assessments.length ? (
        <article className="surface-card p-5 text-brand-muted">No completed evaluation is available yet.</article>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {assessments.map((option) => (
            <article key={option.option_id} className="surface-card p-5">
              <div className="flex justify-between gap-3">
                <h2 className="text-lg font-semibold text-brand-text">{option.option_title}</h2>
                <span className="rounded-lg bg-brand-soft px-3 py-1 text-xs font-medium capitalize text-brand-muted">{option.fit} fit</span>
              </div>
              <div className="mt-4 grid gap-3 text-sm">
                <div><h3 className="font-medium text-brand-success">Strengths</h3><ul className="mt-1 list-disc pl-5 text-brand-muted">{option.strengths.map((item) => <li key={item}>{item}</li>)}</ul></div>
                <div><h3 className="font-medium text-brand-warning">Trade-offs</h3><ul className="mt-1 list-disc pl-5 text-brand-muted">{option.tradeoffs.map((item) => <li key={item}>{item}</li>)}</ul></div>
                {!!option.constraint_conflicts.length && <div><h3 className="font-medium text-red-700">Constraint conflicts</h3><ul className="mt-1 list-disc pl-5 text-red-700">{option.constraint_conflicts.map((item) => <li key={item}>{item}</li>)}</ul></div>}
              </div>
            </article>
          ))}
        </div>
      )}
      {!!recommendation?.key_risks?.length && <article className="surface-card mt-4 p-5"><h2 className="font-semibold text-brand-text">Key risks</h2><div className="mt-3 grid gap-2">{recommendation.key_risks.map((risk) => <div key={risk.id ?? risk.title} className="surface-panel p-3 text-sm"><div className="flex justify-between"><p className="font-medium text-brand-text">{risk.title}</p><span className="capitalize text-brand-muted">{risk.severity} · {risk.likelihood}</span></div><p className="mt-1 text-brand-muted">{risk.description}</p>{risk.mitigation && <p className="mt-1 text-brand-muted">Mitigation: {risk.mitigation}</p>}</div>)}</div></article>}
      <div className="mt-4 flex gap-2"><Link href={`/decision/${decision.id}`} className="rounded-lg border border-brand-border bg-white px-4 py-2 text-sm font-medium">Back to decision</Link>{decision.recommendation && <Link href={`/decision/report?id=${decision.id}`} className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white">View report</Link>}</div>
    </section>
  );
}
