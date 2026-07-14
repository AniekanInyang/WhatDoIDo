import { PageHeader } from "@/components/page-header";
import { AuthInput } from "@/components/auth-input";
import Link from "next/link";
import { signIn } from "./actions";

type AuthPageProps = { searchParams: { error?: string; message?: string; next?: string } };

export default function AuthPage({ searchParams }: AuthPageProps) {
  return (
    <section className="mx-auto max-w-2xl">
      <PageHeader eyebrow="Auth" title="Sign in" subtitle="Access your workspace" />

      {(searchParams.error || searchParams.message) && (
        <p className={`mb-4 rounded-lg border p-3 text-sm ${searchParams.error ? "border-red-200 bg-red-50 text-red-700" : "border-brand-border bg-brand-soft text-brand-text"}`}>
          {searchParams.error ?? searchParams.message}
        </p>
      )}

      <div className="grid gap-4">
        <form action={signIn} className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Sign In</h3>
          <div className="mt-3 grid gap-2 text-sm">
            <AuthInput id="sign-in-email" name="email" placeholder="Email" type="email" autoComplete="email" nextId="sign-in-password" />
            <AuthInput id="sign-in-password" name="password" placeholder="Password" type="password" autoComplete="current-password" />
            <div className="text-right">
              <Link className="text-sm font-medium text-brand-primary hover:underline" href="/auth/forgot-password">
                Forgot your password?
              </Link>
            </div>
            <input name="next" type="hidden" value={searchParams.next ?? ""} />
            <button className="rounded-lg bg-brand-primary px-4 py-2 font-medium text-white hover:bg-brand-hover">
              Continue
            </button>
          </div>
          <p className="mt-4 text-sm text-brand-muted">
            Don&apos;t have an account?{" "}
            <Link className="font-medium text-brand-primary hover:underline" href="/auth/sign-up">
              Create an account
            </Link>
          </p>
        </form>
      </div>

    </section>
  );
}
