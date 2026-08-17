import Link from "next/link";
import { PageHeader } from "@/components/page-header";
import { ConfirmDeleteButton, HistoryBackButton } from "@/components/history-controls";
import { HistorySearch } from "@/components/history-search";
import { listCollections, listDecisions } from "@/lib/api/decisions";
import {
  createCollection,
  deleteCollection,
  moveDecision,
  permanentlyDeleteDecision,
  renameCollection,
  restoreDecision,
  trashDecision,
} from "./actions";

type HistoryProps = {
  searchParams: { q?: string; collection?: string; trash?: string; cursor?: string };
};

function historyHref(values: { q?: string; collection?: string; trash?: boolean; cursor?: string }) {
  const params = new URLSearchParams();
  if (values.q) params.set("q", values.q);
  if (values.collection) params.set("collection", values.collection);
  if (values.trash) params.set("trash", "1");
  if (values.cursor) params.set("cursor", values.cursor);
  const query = params.toString();
  return query ? `/history?${query}` : "/history";
}

export default async function HistoryPage({ searchParams }: HistoryProps) {
  const trash = searchParams.trash === "1";
  const uncategorized = searchParams.collection === "uncategorized";
  const collectionId = !trash && !uncategorized ? searchParams.collection : undefined;
  const [page, collections] = await Promise.all([
    listDecisions({
      q: searchParams.q,
      collectionId,
      uncategorized: !trash && uncategorized,
      trash,
      cursor: searchParams.cursor,
    }),
    listCollections(),
  ]);

  return (
    <section>
      <PageHeader eyebrow="History" title={trash ? "Trash" : "Your Decisions"} subtitle="Search and organize your saved decisions." />

      <div className="mb-4">
        <HistorySearch initialValue={searchParams.q ?? ""} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[0.32fr_1fr]">
        <aside className="surface-card p-4">
          <h3 className="text-sm font-semibold text-brand-text">Collections</h3>
          <nav className="mt-3 grid gap-1 text-sm">
            <Link className="pill rounded-lg px-3 py-2" href={historyHref({ q: searchParams.q })}>All decisions</Link>
            <Link className="pill rounded-lg px-3 py-2" href={historyHref({ q: searchParams.q, collection: "uncategorized" })}>Uncategorized</Link>
            {collections.map((collection) => (
              <details key={collection.id} className="rounded-lg border border-brand-border px-3 py-2">
                <summary className="cursor-pointer font-medium text-brand-text">{collection.name}</summary>
                <div className="mt-2 grid gap-2">
                  <Link className="text-brand-primary hover:underline" href={historyHref({ q: searchParams.q, collection: collection.id })}>View collection</Link>
                  <form action={renameCollection} className="flex gap-1">
                    <input type="hidden" name="id" value={collection.id} />
                    <input name="name" defaultValue={collection.name} className="field min-w-0 flex-1 p-2 text-xs" required maxLength={100} />
                    <button className="pill rounded-lg px-2 text-xs">Rename</button>
                  </form>
                  <form action={deleteCollection}>
                    <input type="hidden" name="id" value={collection.id} />
                    <button className="text-xs font-medium text-red-700 hover:underline">Delete collection</button>
                  </form>
                </div>
              </details>
            ))}
            <Link className="mt-2 rounded-lg px-3 py-2 text-red-700 hover:bg-red-50" href={historyHref({ q: searchParams.q, trash: true })}>Trash</Link>
          </nav>

          <form action={createCollection} className="mt-4 grid gap-2 border-t border-brand-border pt-4">
            <input name="name" className="field p-2.5 text-sm" placeholder="New collection" required maxLength={100} />
            <button className="rounded-lg bg-brand-primary px-3 py-2 text-sm font-medium text-white">Create collection</button>
          </form>
        </aside>

        <article className="surface-card p-4">
          <div className="grid gap-3">
            {page.items.length === 0 && (
              <div className="surface-panel p-8 text-center text-sm text-brand-muted">
                {trash ? "Trash is empty." : searchParams.q ? "No decisions match your search." : "No decisions here yet."}
              </div>
            )}
            {page.items.map((decision) => (
              <div key={decision.id} className="surface-panel p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="text-[11px] uppercase tracking-[0.15em] text-brand-muted">
                      {decision.collection_name ?? "Uncategorized"}
                    </p>
                    <Link href={`/decision/${decision.id}`} className="mt-1 block text-base font-semibold text-brand-text hover:text-brand-primary">
                      {decision.title}
                    </Link>
                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-brand-muted">{decision.prompt}</p>
                  </div>
                  <span className="shrink-0 text-xs text-brand-muted">{new Date(decision.updated_at).toLocaleDateString()}</span>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-brand-border pt-3">
                  {trash ? (
                    <>
                      <form action={restoreDecision}>
                        <input type="hidden" name="id" value={decision.id} />
                        <button className="pill rounded-lg px-3 py-2 text-xs font-medium">Restore</button>
                      </form>
                      <form action={permanentlyDeleteDecision}>
                        <input type="hidden" name="id" value={decision.id} />
                        <ConfirmDeleteButton className="rounded-lg px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-50">Delete permanently</ConfirmDeleteButton>
                      </form>
                    </>
                  ) : (
                    <>
                      <form action={moveDecision} className="flex items-center gap-2">
                        <input type="hidden" name="decisionId" value={decision.id} />
                        <select name="collectionId" defaultValue={decision.collection_id ?? ""} className="field p-2 text-xs">
                          <option value="">Uncategorized</option>
                          {collections.map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}
                        </select>
                        <button className="pill rounded-lg px-3 py-2 text-xs font-medium">Move</button>
                      </form>
                      <form action={trashDecision} className="ml-auto">
                        <input type="hidden" name="id" value={decision.id} />
                        <button className="rounded-lg px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-50">Move to Trash</button>
                      </form>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>

          {(searchParams.cursor || page.next_cursor) && (
            <div className="mt-4 flex items-center justify-between border-t border-brand-border pt-4">
              {searchParams.cursor ? <HistoryBackButton /> : <span />}
              {page.next_cursor && (
                <Link className="rounded-lg bg-brand-primary px-3 py-2 text-sm font-medium text-white" href={historyHref({ q: searchParams.q, collection: searchParams.collection, trash, cursor: page.next_cursor })}>Next</Link>
              )}
            </div>
          )}
        </article>
      </div>
    </section>
  );
}
