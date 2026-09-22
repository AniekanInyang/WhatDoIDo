import { PageHeader } from "@/components/page-header";
import { ConversationComposer } from "@/components/conversation-composer";
import { getDecision } from "@/lib/api/decisions";
import Link from "next/link";
import { createOption, deleteOption, renameDecision, resolveContradiction, retryWorkflow, reviewBriefItem, reviewOption, sendMessage, updateOption } from "./actions";

type BriefItem = {
  id: string;
  value?: unknown;
  name?: string;
  statement?: string;
  title?: string;
  description?: string;
  importance?: number | string;
  severity?: string;
  likelihood?: string;
  mitigation?: string | null;
  source?: string;
  confidence?: string;
  status?: string;
  evidence_message_ids?: string[];
};

function ReviewableItems({ decisionId, collection, title, items, readOnly }: {
  decisionId: string;
  collection: string;
  title: string;
  items: BriefItem[];
  readOnly: boolean;
}) {
  if (!items.length) return null;
  return (
    <div className="surface-panel p-3">
      <p className="font-medium text-brand-text">{title}</p>
      <div className="mt-2 grid gap-2">
        {items.filter((item) => item.status !== "rejected" && item.status !== "superseded").map((item) => {
          const label = String(item.value ?? item.name ?? item.statement ?? item.title ?? "");
          return (
            <div key={item.id} className="rounded-lg border border-brand-border bg-white p-2">
              <p className="text-brand-text">{label}</p>
              {item.description && <p className="mt-1 text-xs text-brand-muted">{item.description}</p>}
              <p className="mt-1 text-[11px] capitalize text-brand-muted">
                {item.source ?? "unknown source"} · {item.confidence ?? "unknown"} confidence · {item.status ?? "confirmed"}
                {item.importance ? ` · importance ${item.importance}` : ""}
                {item.severity ? ` · ${item.severity} severity` : ""}
                {item.likelihood ? ` · ${item.likelihood}` : ""}
              </p>
              {!!item.evidence_message_ids?.length && <p className="mt-1 text-[11px] text-brand-muted">Evidence: {item.evidence_message_ids.length} conversation message(s)</p>}
              {item.mitigation && <p className="mt-1 text-xs text-brand-muted">Mitigation: {item.mitigation}</p>}
              {!readOnly && item.status === "candidate" && (
                <div className="mt-2 flex gap-2">
                  <form action={reviewBriefItem.bind(null, decisionId, collection, item.id, "confirmed")}>
                    <button className="rounded-md bg-brand-primary px-2 py-1 text-xs font-medium text-white">Confirm</button>
                  </form>
                  <form action={reviewBriefItem.bind(null, decisionId, collection, item.id, "rejected")}>
                    <button className="rounded-md border border-brand-border px-2 py-1 text-xs font-medium text-brand-muted">Reject</button>
                  </form>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}


export default async function SavedDecisionPage({ params, searchParams }: {
  params: { id: string };
  searchParams?: { retry_error?: string };
}) {
  const decision = await getDecision(params.id);
  const renameAction = renameDecision.bind(null, decision.id);
  const sendAction = sendMessage.bind(null, decision.id);
  const createOptionAction = createOption.bind(null, decision.id);
  const brief = decision.decision_brief as {
    goal?: BriefItem;
    values?: BriefItem[];
    constraints?: BriefItem[];
    domain?: BriefItem;
    deadline?: BriefItem;
    uncertainties?: BriefItem[];
    criteria?: BriefItem[];
    risk_tolerance?: BriefItem;
    preference_signals?: BriefItem[];
    assumptions?: BriefItem[];
    risks?: BriefItem[];
    contradictions?: Array<{ id: string; topic: string; previous_value: string; new_value: string; status: string }>;
    readiness?: { score?: number };
  };
  const recommendation = decision.recommendation as null | {
    selected_option_title?: string;
    summary?: string;
    rationale?: string[];
    robustness?: "low" | "moderate" | "high";
    assumptions?: string[];
    unresolved_uncertainties?: string[];
    caveat?: string | null;
    option_assessments?: Array<{
      option_id: string;
      option_title: string;
      fit: string;
      strengths: string[];
      tradeoffs: string[];
      constraint_conflicts: string[];
    }>;
    sensitivity_analysis?: Array<{
      factor: string;
      current_assumption: string;
      change_that_could_flip_result: string;
      explanation: string;
    }>;
  };
  const latestAssistant = [...decision.messages].reverse().find((message) => message.role === "assistant");
  const awaitingReply = decision.status !== "completed"
    && decision.messages.length > 0
    && decision.messages[decision.messages.length - 1]?.role === "user";
  const retryAvailable = latestAssistant?.structured_data?.retry_available === true && decision.status !== "completed";
  const visibleOptions = decision.options.filter((option) => option.status !== "rejected");

  return (
    <section className="mx-auto max-w-5xl">
      <PageHeader eyebrow="Conversation" title={decision.title} subtitle={`Status: ${decision.status}`} />

      {searchParams?.retry_error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {searchParams.retry_error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1.45fr_0.75fr]">
        <article className="surface-card p-5">
          <ConversationComposer
            action={sendAction}
            messages={decision.messages}
            awaitingReply={awaitingReply}
            readOnly={decision.status === "completed" || retryAvailable}
            readOnlyMessage={retryAvailable ? "The workflow is paused at a failed stage. Retry it before sending another message." : undefined}
          />
          {retryAvailable && <form action={retryWorkflow.bind(null, decision.id)} className="mt-3"><button className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white">Retry workflow</button></form>}
        </article>

        <aside className="surface-card p-5">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-base font-semibold text-brand-text">Decision Brief</h3>
            <span className="rounded-lg bg-brand-soft px-2.5 py-1 text-xs font-medium text-brand-muted">
              {Object.keys(decision.decision_brief).length ? "In progress" : "Gathering"}
            </span>
          </div>
          <div className="mt-4 grid gap-2 text-sm">
            <div className="surface-panel p-3">
              <p className="font-medium text-brand-text">Decision</p>
              <p className="mt-1 text-brand-muted">{String(brief.goal?.value ?? decision.prompt)}</p>
              <p className="mt-1 text-[11px] capitalize text-brand-muted">
                {brief.goal?.source ?? "explicit"} · {brief.goal?.confidence ?? "high"} confidence
              </p>
              {!!brief.goal?.evidence_message_ids?.length && <p className="mt-1 text-[11px] text-brand-muted">Evidence: {brief.goal.evidence_message_ids.length} conversation message(s)</p>}
              {brief.domain?.value != null && <p className="mt-2 text-xs text-brand-muted">Domain: {String(brief.domain.value)} · {brief.domain.source} · {brief.domain.confidence} confidence</p>}
              {brief.deadline?.value != null && <p className="mt-1 text-xs text-brand-muted">Deadline: {String(brief.deadline.value)} · {brief.deadline.source} · {brief.deadline.confidence} confidence</p>}
            </div>
            <div className="surface-panel p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="font-medium text-brand-text">Options</p>
                <span className="text-xs text-brand-muted">{visibleOptions.length} captured</span>
              </div>
              <div className="mt-2 grid gap-2">
                {visibleOptions.map((option) => (
                  <details key={option.id} className="rounded-lg border border-brand-border bg-white p-2">
                    <summary className="cursor-pointer font-medium text-brand-text">
                      {option.title}
                      <span className="ml-2 text-xs font-normal text-brand-muted">
                        {option.source === "ai_generated" ? "Suggested" : option.source === "ai_extracted" ? "Extracted" : "Added by you"}
                      </span>
                    </summary>
                    {option.description && <p className="mt-1 text-xs text-brand-muted">{option.description}</p>}
                    <p className="mt-1 text-[11px] capitalize text-brand-muted">{option.status}</p>
                    {decision.status !== "completed" && option.status === "candidate" && (
                      <div className="mt-2 flex gap-2">
                        <form action={reviewOption.bind(null, decision.id, option.id, "confirmed")}>
                          <button className="rounded-md bg-brand-primary px-2 py-1 text-xs font-medium text-white">Confirm</button>
                        </form>
                        <form action={reviewOption.bind(null, decision.id, option.id, "rejected")}>
                          <button className="rounded-md border border-brand-border px-2 py-1 text-xs font-medium text-brand-muted">Reject</button>
                        </form>
                      </div>
                    )}
                    {decision.status !== "completed" && (
                      <div className="mt-3 grid gap-2">
                        <form action={updateOption.bind(null, decision.id, option.id)} className="grid gap-2">
                          <input name="title" defaultValue={option.title} className="field p-2 text-xs" required maxLength={200} />
                          <textarea name="description" defaultValue={option.description ?? ""} className="field p-2 text-xs" maxLength={2000} rows={2} />
                          <button className="rounded-lg border border-brand-border px-3 py-2 text-xs font-medium">Save option</button>
                        </form>
                        <form action={deleteOption.bind(null, decision.id, option.id)}>
                          <button className="text-xs font-medium text-red-700">Remove option</button>
                        </form>
                      </div>
                    )}
                  </details>
                ))}
                {!visibleOptions.length && <p className="text-brand-muted">Being explored in conversation</p>}
              </div>
            </div>
            <ReviewableItems decisionId={decision.id} collection="values" title="What matters" items={brief.values ?? []} readOnly={decision.status === "completed"} />
            <ReviewableItems decisionId={decision.id} collection="constraints" title="Constraints" items={brief.constraints ?? []} readOnly={decision.status === "completed"} />
            <ReviewableItems decisionId={decision.id} collection="criteria" title="Criteria" items={brief.criteria ?? []} readOnly={decision.status === "completed"} />
            <ReviewableItems decisionId={decision.id} collection="uncertainties" title="Uncertainties" items={brief.uncertainties ?? []} readOnly={decision.status === "completed"} />
            <ReviewableItems decisionId={decision.id} collection="preference_signals" title="Preference signals" items={brief.preference_signals ?? []} readOnly={decision.status === "completed"} />
            <ReviewableItems decisionId={decision.id} collection="assumptions" title="Assumptions to confirm" items={brief.assumptions ?? []} readOnly={decision.status === "completed"} />
            <ReviewableItems decisionId={decision.id} collection="risks" title="Risks" items={brief.risks ?? []} readOnly={decision.status === "completed"} />
            {brief.risk_tolerance?.value != null && (
              <div className="surface-panel p-3">
                <p className="font-medium text-brand-text">Risk tolerance</p>
                <p className="mt-1 text-brand-muted">{String(brief.risk_tolerance.value)}</p>
                <p className="mt-1 text-[11px] capitalize text-brand-muted">{brief.risk_tolerance.source} · {brief.risk_tolerance.confidence} confidence</p>
                {!!brief.risk_tolerance.evidence_message_ids?.length && <p className="mt-1 text-[11px] text-brand-muted">Evidence: {brief.risk_tolerance.evidence_message_ids.length} conversation message(s)</p>}
              </div>
            )}
            {!!brief.contradictions?.filter((item) => item.status === "unresolved").length && (
              <div className="rounded-xl border border-amber-300 bg-amber-50 p-3">
                <p className="font-medium text-amber-900">Changed answers to resolve</p>
                <div className="mt-2 grid gap-3">
                  {brief.contradictions.filter((item) => item.status === "unresolved").map((item) => (
                    <div key={item.id} className="text-xs text-amber-900">
                      <p className="font-medium capitalize">{item.topic}</p>
                      <p className="mt-1">Earlier: {item.previous_value}</p>
                      <p>Latest: {item.new_value}</p>
                      {decision.status !== "completed" && <div className="mt-2 flex gap-2">
                        <form action={resolveContradiction.bind(null, decision.id, item.id, "previous")}><button className="rounded-md border border-amber-400 px-2 py-1">Use earlier</button></form>
                        <form action={resolveContradiction.bind(null, decision.id, item.id, "new")}><button className="rounded-md bg-amber-800 px-2 py-1 text-white">Use latest</button></form>
                      </div>}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {decision.status !== "completed" && (
              <details className="surface-panel p-3">
                <summary className="cursor-pointer font-medium text-brand-text">Add an option</summary>
                <form action={createOptionAction} className="mt-3 grid gap-2">
                  <input name="title" placeholder="Option title" className="field p-2 text-sm" required maxLength={200} />
                  <textarea name="description" placeholder="Description (optional)" className="field p-2 text-sm" rows={2} maxLength={2000} />
                  <button className="rounded-lg bg-brand-primary px-3 py-2 text-sm font-medium text-white">Add option</button>
                </form>
              </details>
            )}
          </div>

          <details className="mt-5 border-t border-brand-border pt-4">
            <summary className="cursor-pointer text-sm font-medium text-brand-text">Edit title</summary>
            <form action={renameAction} className="mt-3 grid gap-2">
              <input name="title" defaultValue={decision.title} className="field p-3 text-sm" maxLength={200} required />
              <button className="rounded-lg border border-brand-border bg-brand-soft px-4 py-2.5 text-sm font-medium text-brand-text hover:border-brand-accent">
                Save title
              </button>
            </form>
          </details>
        </aside>
      </div>

      {recommendation && (
        <article className="surface-card mt-4 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-brand-muted">Recommendation</p>
              <h2 className="mt-1 text-2xl font-semibold text-brand-text">{recommendation.selected_option_title}</h2>
            </div>
            <span className="rounded-lg bg-brand-soft px-3 py-1.5 text-xs font-medium capitalize text-brand-muted">
              {recommendation.robustness ?? "unknown"} robustness
            </span>
          </div>
          <p className="mt-3 leading-7 text-brand-muted">{recommendation.summary}</p>

          {!!recommendation.rationale?.length && (
            <section className="mt-5">
              <h3 className="font-semibold text-brand-text">Why this option</h3>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-brand-muted">
                {recommendation.rationale.map((reason) => <li key={reason}>{reason}</li>)}
              </ul>
            </section>
          )}

          {!!recommendation.option_assessments?.length && (
            <section className="mt-5">
              <h3 className="font-semibold text-brand-text">Option comparison</h3>
              <div className="mt-2 grid gap-3 md:grid-cols-2">
                {recommendation.option_assessments.map((assessment) => (
                  <div key={assessment.option_id} className="surface-panel p-3 text-sm">
                    <div className="flex justify-between gap-2">
                      <p className="font-medium text-brand-text">{assessment.option_title}</p>
                      <span className="capitalize text-brand-muted">{assessment.fit} fit</span>
                    </div>
                    {!!assessment.strengths.length && <p className="mt-2 text-brand-muted"><strong>Strengths:</strong> {assessment.strengths.join(" · ")}</p>}
                    {!!assessment.tradeoffs.length && <p className="mt-1 text-brand-muted"><strong>Trade-offs:</strong> {assessment.tradeoffs.join(" · ")}</p>}
                    {!!assessment.constraint_conflicts.length && <p className="mt-1 text-red-700"><strong>Conflicts:</strong> {assessment.constraint_conflicts.join(" · ")}</p>}
                  </div>
                ))}
              </div>
            </section>
          )}

          {!!recommendation.sensitivity_analysis?.length && (
            <section className="mt-5">
              <h3 className="font-semibold text-brand-text">What could change the recommendation</h3>
              <div className="mt-2 grid gap-2">
                {recommendation.sensitivity_analysis.map((driver) => (
                  <div key={`${driver.factor}-${driver.change_that_could_flip_result}`} className="surface-panel p-3 text-sm">
                    <p className="font-medium text-brand-text">{driver.factor}</p>
                    <p className="mt-1 text-brand-muted">Currently: {driver.current_assumption}</p>
                    <p className="mt-1 text-brand-muted">Could flip if: {driver.change_that_could_flip_result}</p>
                    <p className="mt-1 text-brand-muted">{driver.explanation}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {(recommendation.caveat || !!recommendation.unresolved_uncertainties?.length || !!recommendation.assumptions?.length) && (
            <details className="mt-5 border-t border-brand-border pt-4">
              <summary className="cursor-pointer font-medium text-brand-text">Assumptions and uncertainties</summary>
              {recommendation.caveat && <p className="mt-2 text-sm text-brand-muted">{recommendation.caveat}</p>}
              {!!recommendation.assumptions?.length && <p className="mt-2 text-sm text-brand-muted"><strong>Assumptions:</strong> {recommendation.assumptions.join(" · ")}</p>}
              {!!recommendation.unresolved_uncertainties?.length && <p className="mt-2 text-sm text-brand-muted"><strong>Still uncertain:</strong> {recommendation.unresolved_uncertainties.join(" · ")}</p>}
            </details>
          )}
        </article>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        {!!decision.evaluations.length && <Link href={`/decision/evaluation?id=${decision.id}`} className="rounded-lg border border-brand-border bg-white px-4 py-2 text-sm font-medium text-brand-text">Open Evaluation</Link>}
        {recommendation && <Link href={`/decision/report?id=${decision.id}`} className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-medium text-white">Open Report</Link>}
      </div>
    </section>
  );
}
