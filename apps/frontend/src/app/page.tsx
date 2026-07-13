import Link from "next/link";
import { PageHeader } from "@/components/page-header";

export default function LandingPage() {
  return (
    <section className="mx-auto max-w-3xl">
      <PageHeader eyebrow="Home" title="Make better decisions, faster" subtitle="Clear conversation. Clean report." />

      <div className="grid gap-4">
        <article className="surface-card p-5 text-center">
          <h3 className="text-xl font-semibold text-brand-text">Start with one question</h3>
          <p className="mt-2 text-sm text-brand-muted">What decision are you trying to make?</p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <Link
              href="/decision/conversation"
              className="rounded-xl bg-brand-primary px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-hover"
            >
              Start a New Decision
            </Link>
          </div>
        </article>
      </div>
    </section>
  );
}
