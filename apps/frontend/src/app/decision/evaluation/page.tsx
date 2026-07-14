import { PageHeader } from "@/components/page-header";

const options = [
  { name: "Join startup", upside: "High learning speed", downside: "Income volatility", score: 82, risk: "Moderate" },
  { name: "Stay current role", upside: "Financial stability", downside: "Slower growth", score: 74, risk: "Low" },
  { name: "Negotiate hybrid path", upside: "Balanced risk", downside: "Execution complexity", score: 79, risk: "Medium" },
];

export default function EvaluationBoardPage() {
  return (
    <section>
      <PageHeader eyebrow="Evaluation" title="Option Board" subtitle="Compare options by upside, downside, risk, and score." />

      <div className="grid gap-3 md:hidden">
        {options.map((option) => (
          <article key={option.name} className="surface-card p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.15em] text-brand-muted">Option</p>
                <h3 className="mt-1 text-lg font-semibold text-brand-text">{option.name}</h3>
              </div>
              <span className="rounded-lg bg-brand-primary px-3 py-1.5 text-sm font-semibold text-white">{option.score}</span>
            </div>
            <div className="mt-4 grid gap-2">
              <div className="surface-panel p-3">
                <p className="text-xs font-medium text-brand-success">Upside</p>
                <p className="mt-1 text-sm text-brand-text">{option.upside}</p>
              </div>
              <div className="surface-panel p-3">
                <p className="text-xs font-medium text-brand-warning">Downside</p>
                <p className="mt-1 text-sm text-brand-text">{option.downside}</p>
              </div>
              <div className="surface-panel p-3">
                <p className="text-xs font-medium text-brand-muted">Risk</p>
                <p className="mt-1 text-sm text-brand-text">{option.risk}</p>
              </div>
            </div>
          </article>
        ))}
      </div>

      <article className="surface-card hidden overflow-hidden md:block">
        <table className="w-full border-collapse text-sm">
          <thead className="bg-brand-soft text-left text-brand-muted">
            <tr>
              <th className="px-4 py-3 font-medium">Option</th>
              <th className="px-4 py-3 font-medium">Upside</th>
              <th className="px-4 py-3 font-medium">Downside</th>
              <th className="px-4 py-3 font-medium">Risk</th>
              <th className="px-4 py-3 font-medium">Score</th>
            </tr>
          </thead>
          <tbody>
            {options.map((option) => (
              <tr key={option.name} className="border-t border-brand-border">
                <td className="px-4 py-3 font-semibold text-brand-text">{option.name}</td>
                <td className="px-4 py-3 text-brand-success">{option.upside}</td>
                <td className="px-4 py-3 text-brand-warning">{option.downside}</td>
                <td className="px-4 py-3 text-brand-muted">{option.risk}</td>
                <td className="px-4 py-3">
                  <span className="rounded-lg bg-brand-soft px-3 py-1 text-brand-text">{option.score}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </article>
    </section>
  );
}
