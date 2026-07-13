import { PageHeader } from "@/components/page-header";

const options = [
  { name: "Join startup", upside: "High learning speed", downside: "Income volatility", score: 82 },
  { name: "Stay current role", upside: "Financial stability", downside: "Slower growth", score: 74 },
  { name: "Negotiate hybrid path", upside: "Balanced risk", downside: "Execution complexity", score: 79 },
];

export default function EvaluationBoardPage() {
  return (
    <section>
      <PageHeader eyebrow="Evaluation" title="Option Board" subtitle="Quick comparison" />

      <article className="surface-card overflow-hidden">
        <table className="w-full border-collapse text-sm">
          <thead className="bg-brand-soft text-left text-brand-muted">
            <tr>
              <th className="px-4 py-3 font-medium">Option</th>
              <th className="px-4 py-3 font-medium">Upside</th>
              <th className="px-4 py-3 font-medium">Downside</th>
              <th className="px-4 py-3 font-medium">Score</th>
            </tr>
          </thead>
          <tbody>
            {options.map((option) => (
              <tr key={option.name} className="border-t border-brand-border">
                <td className="px-4 py-3 font-semibold text-brand-text">{option.name}</td>
                <td className="px-4 py-3 text-brand-muted">{option.upside}</td>
                <td className="px-4 py-3 text-brand-muted">{option.downside}</td>
                <td className="px-4 py-3">
                  <span className="rounded-full bg-brand-soft px-3 py-1 text-brand-text">{option.score}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </article>
    </section>
  );
}
