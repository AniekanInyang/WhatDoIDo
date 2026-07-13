import { PageHeader } from "@/components/page-header";

const timeline = [
  { step: "Parse dilemma", note: "Detected tradeoff between growth and stability." },
  { step: "Clarification", note: "Captured salary floor and relocation constraint." },
  { step: "Option generation", note: "Generated 3 actionable paths." },
  { step: "Critique", note: "Stress-tested recommendation against downside cases." },
  { step: "Final report", note: "Produced recommendation with confidence 0.78." },
];

export default function DecisionDetailPage() {
  return (
    <section>
      <PageHeader eyebrow="Decision Detail" title="Run D-1024" subtitle="Step-by-step trace" />

      <article className="surface-card p-5">
        <div className="grid gap-3">
          {timeline.map((item, index) => (
            <div key={item.step} className="surface-panel flex gap-3 p-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-primary text-sm font-semibold text-white">
                {index + 1}
              </div>
              <div>
                <h3 className="text-sm font-semibold text-brand-text">{item.step}</h3>
                <p className="mt-0.5 text-xs text-brand-muted">{item.note}</p>
              </div>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}
