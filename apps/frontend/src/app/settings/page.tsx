import { PageHeader } from "@/components/page-header";

export default function SettingsPage() {
  return (
    <section>
      <PageHeader eyebrow="Settings" title="Profile & Preferences" subtitle="Manage your defaults" />

      <div className="grid gap-4 xl:grid-cols-2">
        <article className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Profile</h3>
          <div className="mt-3 grid gap-2">
            <input className="field p-3 text-sm" placeholder="Display name" />
            <input className="field p-3 text-sm" placeholder="Email" />
          </div>
        </article>

        <article className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Defaults</h3>
          <div className="mt-3 grid gap-2 text-sm text-brand-muted">
            <label className="surface-panel p-3">Risk: Moderate</label>
            <label className="surface-panel p-3">Report: Detailed</label>
            <label className="surface-panel p-3">Confidence notes: On</label>
          </div>
        </article>
      </div>
    </section>
  );
}
