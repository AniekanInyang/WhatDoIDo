import { PageHeader } from "@/components/page-header";
import { getDecision } from "@/lib/api/decisions";
import Link from "next/link";
import { redirect } from "next/navigation";

export default async function RecommendationReportPage({ searchParams }: { searchParams: { id?: string } }) {
  if (!searchParams.id) redirect("/history");
  const decision = await getDecision(searchParams.id);
  const report = decision.recommendation as null | {
    selected_option_title: string; summary: string; robustness: string; rationale: string[];
    checks_before_acting?: string[]; alternate_recommendation?: string | null;
    assumptions?: string[]; unresolved_uncertainties?: string[];
    sensitivity_analysis?: Array<{ factor: string; current_assumption: string; change_that_could_flip_result: string; explanation: string }>;
    key_risks?: Array<{ id?: string; title: string; description: string; severity: string; likelihood: string; mitigation?: string | null }>;
    caveat?: string | null;
  };

  return (
    <section>
      <PageHeader eyebrow="Report" title={decision.title} subtitle="The recommendation, key risks, action checks, and conditions that could change the answer." />
      {!report ? <article className="surface-card p-5 text-brand-muted">This decision does not have a completed recommendation yet.</article> : <>
        <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
          <article className="surface-card p-5"><p className="text-[11px] uppercase tracking-[0.18em] text-brand-muted">Top recommendation</p><h2 className="mt-2 text-2xl font-semibold text-brand-text">{report.selected_option_title}</h2><p className="mt-3 leading-7 text-brand-muted">{report.summary}</p><span className="mt-4 inline-block rounded-lg bg-brand-soft px-3 py-1.5 text-xs font-medium capitalize text-brand-muted">{report.robustness} robustness</span><h3 className="mt-5 font-semibold text-brand-text">Why</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-brand-muted">{report.rationale.map((item) => <li key={item}>{item}</li>)}</ul>{report.caveat && <p className="mt-4 rounded-lg bg-brand-soft p-3 text-sm text-brand-muted">{report.caveat}</p>}</article>
          <article className="surface-card p-5"><h2 className="font-semibold text-brand-text">Checks before acting</h2>{report.checks_before_acting?.length ? <ul className="mt-3 grid gap-2 text-sm text-brand-muted">{report.checks_before_acting.map((check) => <li key={check} className="surface-panel p-2">{check}</li>)}</ul> : <p className="mt-2 text-sm text-brand-muted">No additional checks were identified.</p>}<h3 className="mt-5 text-xs font-semibold uppercase tracking-[0.15em] text-brand-muted">Alternate</h3><p className="mt-2 text-sm text-brand-text">{report.alternate_recommendation ?? "No distinct alternate recommendation was identified."}</p></article>
        </div>
        {!!report.key_risks?.length && <article className="surface-card mt-4 p-5"><h2 className="font-semibold text-brand-text">Key risks</h2><div className="mt-3 grid gap-2 md:grid-cols-2">{report.key_risks.map((risk) => <div key={risk.id ?? risk.title} className="surface-panel p-3 text-sm"><div className="flex justify-between gap-2"><p className="font-medium text-brand-text">{risk.title}</p><span className="capitalize text-brand-muted">{risk.severity} · {risk.likelihood}</span></div><p className="mt-1 text-brand-muted">{risk.description}</p>{risk.mitigation && <p className="mt-1 text-brand-muted">Mitigation: {risk.mitigation}</p>}</div>)}</div></article>}
        {!!report.sensitivity_analysis?.length && <article className="surface-card mt-4 p-5"><h2 className="font-semibold text-brand-text">What could change the answer</h2><div className="mt-3 grid gap-2">{report.sensitivity_analysis.map((item) => <div key={`${item.factor}-${item.change_that_could_flip_result}`} className="surface-panel p-3 text-sm"><p className="font-medium text-brand-text">{item.factor}</p><p className="mt-1 text-brand-muted">Current assumption: {item.current_assumption}</p><p className="mt-1 text-brand-muted">Could change if: {item.change_that_could_flip_result}</p><p className="mt-1 text-brand-muted">{item.explanation}</p></div>)}</div></article>}
        <details className="surface-card mt-4 p-5"><summary className="cursor-pointer font-semibold text-brand-text">Assumptions and unresolved uncertainties</summary><p className="mt-3 text-sm text-brand-muted"><strong>Assumptions:</strong> {report.assumptions?.join(" · ") || "None recorded"}</p><p className="mt-2 text-sm text-brand-muted"><strong>Uncertainties:</strong> {report.unresolved_uncertainties?.join(" · ") || "None recorded"}</p></details>
      </>}
      <div className="mt-4 flex gap-2"><Link href={`/decision/${decision.id}`} className="rounded-lg border border-brand-border bg-white px-4 py-2 text-sm font-medium">Back to decision</Link><Link href={`/decision/evaluation?id=${decision.id}`} className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white">View evaluation</Link></div>
    </section>
  );
}
