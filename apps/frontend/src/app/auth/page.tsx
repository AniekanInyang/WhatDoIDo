import { PageHeader } from "@/components/page-header";

export default function AuthPage() {
  return (
    <section>
      <PageHeader eyebrow="Auth" title="Sign in" subtitle="Access your workspace" />

      <div className="grid gap-4 lg:grid-cols-2">
        <form className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Sign In</h3>
          <div className="mt-3 grid gap-2 text-sm">
            <input className="field p-3" placeholder="Email" />
            <input className="field p-3" placeholder="Password" type="password" />
            <button className="rounded-lg bg-brand-primary px-4 py-2 font-medium text-white hover:bg-brand-hover">
              Continue
            </button>
          </div>
        </form>

        <form className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Create Account</h3>
          <div className="mt-3 grid gap-2 text-sm">
            <input className="field p-3" placeholder="Name" />
            <input className="field p-3" placeholder="Email" />
            <input className="field p-3" placeholder="Password" type="password" />
            <button className="rounded-lg border border-brand-border bg-brand-soft px-4 py-2 font-medium text-brand-text hover:border-brand-accent">
              Create
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
