import { PageHeader } from "@/components/page-header";
import { ConversationComposer } from "@/components/conversation-composer";
import { getDecision } from "@/lib/api/decisions";
import { renameDecision, sendMessage } from "./actions";


export default async function SavedDecisionPage({ params }: { params: { id: string } }) {
  const decision = await getDecision(params.id);
  const renameAction = renameDecision.bind(null, decision.id);
  const sendAction = sendMessage.bind(null, decision.id);

  return (
    <section className="mx-auto max-w-5xl">
      <PageHeader eyebrow="Conversation" title={decision.title} subtitle={`Status: ${decision.status}`} />

      <div className="grid gap-4 lg:grid-cols-[1.45fr_0.75fr]">
        <article className="surface-card p-5">
          <ConversationComposer action={sendAction} messages={decision.messages} />
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
              <p className="mt-1 text-brand-muted">{decision.prompt}</p>
            </div>
            <div className="surface-panel p-3">
              <p className="font-medium text-brand-text">Options</p>
              <p className="mt-1 text-brand-muted">
                {decision.options.length ? `${decision.options.length} captured` : "Being explored in conversation"}
              </p>
            </div>
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
    </section>
  );
}
