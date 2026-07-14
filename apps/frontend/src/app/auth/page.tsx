import { PageHeader } from "@/components/page-header";
import { AuthInput } from "@/components/auth-input";
import { requestPasswordReset, signIn, signUp } from "./actions";

type AuthPageProps = { searchParams: { error?: string; message?: string; next?: string } };

export default function AuthPage({ searchParams }: AuthPageProps) {
  return (
    <section>
      <PageHeader eyebrow="Auth" title="Sign in" subtitle="Access your workspace" />

      {(searchParams.error || searchParams.message) && (
        <p className={`mb-4 rounded-lg border p-3 text-sm ${searchParams.error ? "border-red-200 bg-red-50 text-red-700" : "border-brand-border bg-brand-soft text-brand-text"}`}>
          {searchParams.error ?? searchParams.message}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <form action={signIn} className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Sign In</h3>
          <div className="mt-3 grid gap-2 text-sm">
            <AuthInput id="sign-in-email" name="email" placeholder="Email" type="email" autoComplete="email" nextId="sign-in-password" />
            <AuthInput id="sign-in-password" name="password" placeholder="Password" type="password" autoComplete="current-password" />
            <input name="next" type="hidden" value={searchParams.next ?? ""} />
            <button className="rounded-lg bg-brand-primary px-4 py-2 font-medium text-white hover:bg-brand-hover">
              Continue
            </button>
          </div>
        </form>

        <form action={signUp} className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Create Account</h3>
          <div className="mt-3 grid gap-2 text-sm">
            <AuthInput id="sign-up-name" name="name" placeholder="Name" type="text" autoComplete="name" nextId="sign-up-email" />
            <AuthInput id="sign-up-email" name="email" placeholder="Email" type="email" autoComplete="email" nextId="sign-up-password" />
            <AuthInput id="sign-up-password" name="password" placeholder="Password (8+ characters)" type="password" minLength={8} autoComplete="new-password" />
            <button className="rounded-lg border border-brand-border bg-brand-soft px-4 py-2 font-medium text-brand-text hover:border-brand-accent">
              Create
            </button>
          </div>
        </form>
      </div>

      <form action={requestPasswordReset} className="surface-card mt-4 flex flex-col gap-2 p-5 sm:flex-row sm:items-end">
        <label className="grid flex-1 gap-2 text-sm font-medium text-brand-text">
          Forgot your password?
          <input name="email" className="field p-3 font-normal" placeholder="Email" type="email" required autoComplete="email" />
        </label>
        <button className="rounded-lg border border-brand-border bg-brand-soft px-4 py-3 text-sm font-medium text-brand-text hover:border-brand-accent">Send reset link</button>
      </form>
    </section>
  );
}
