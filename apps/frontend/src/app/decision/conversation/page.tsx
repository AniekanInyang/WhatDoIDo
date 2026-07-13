import { PageHeader } from "@/components/page-header";

export default function DecisionConversationPage() {
  return (
    <section className="mx-auto max-w-5xl">
      <PageHeader eyebrow="Conversation" title="New Decision" subtitle="Start with the decision you are trying to make. The workspace will fill in as you talk." />

      <div className="grid gap-4 lg:grid-cols-[1.45fr_0.75fr]">
        <article className="surface-card p-5">
          <div className="mb-4 flex flex-col gap-3 border-b border-brand-border pb-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[11px] uppercase tracking-[0.18em] text-brand-muted">Conversation</p>
              <h3 className="mt-1 text-lg font-semibold text-brand-text">Untitled decision</h3>
            </div>
            <span className="w-fit rounded-lg bg-brand-soft px-3 py-2 text-xs font-medium text-brand-muted">
              Not evaluated yet
            </span>
          </div>

          <div className="flex min-h-[44vh] items-center justify-center rounded-lg border border-dashed border-brand-border bg-brand-soft/50 p-6 text-center">
            <div className="max-w-md">
              <p className="text-base font-semibold text-brand-text">What decision do you need help with?</p>
              <p className="mt-2 text-sm leading-6 text-brand-muted">
                Describe the choice in plain language. Once you send the first message, this space becomes the working conversation.
              </p>
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <input
              className="field min-w-0 flex-1 p-3 text-sm"
              placeholder="Example: Should I accept the startup offer or stay where I am?"
            />
            <button className="rounded-lg bg-brand-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-hover">
              Send
            </button>
          </div>
        </article>

        <aside className="surface-card p-5">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-base font-semibold text-brand-text">Decision Brief</h3>
            <span className="rounded-lg bg-brand-soft px-2.5 py-1 text-xs font-medium text-brand-muted">Empty</span>
          </div>
          <div className="mt-4 grid gap-2 text-sm text-brand-muted">
            <div className="surface-panel p-3">
              <p className="font-medium text-brand-text">Decision</p>
              <p>Waiting for your first message.</p>
            </div>
            <div className="surface-panel p-3">
              <p className="font-medium text-brand-text">Options</p>
              <p>None captured yet.</p>
            </div>
            <div className="surface-panel p-3">
              <p className="font-medium text-brand-text">Constraints</p>
              <p>None captured yet.</p>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}
