import Link from "next/link";
import { AuthInput } from "@/components/auth-input";
import { PageHeader } from "@/components/page-header";
import { requestPasswordReset } from "../actions";

type ForgotPasswordPageProps = {
  searchParams: { error?: string; message?: string };
};

export default function ForgotPasswordPage({ searchParams }: ForgotPasswordPageProps) {
  return (
    <section className="mx-auto max-w-2xl">
      <PageHeader
        eyebrow="Auth"
        title="Reset your password"
        subtitle="Enter your email and we’ll send you a password reset link."
      />

      {(searchParams.error || searchParams.message) && (
        <p className={`mb-4 rounded-lg border p-3 text-sm ${searchParams.error ? "border-red-200 bg-red-50 text-red-700" : "border-brand-border bg-brand-soft text-brand-text"}`}>
          {searchParams.error ?? searchParams.message}
        </p>
      )}

      <form action={requestPasswordReset} className="surface-card p-5">
        <div className="grid gap-3 text-sm">
          <label className="font-medium text-brand-text" htmlFor="reset-email">
            Email
          </label>
          <AuthInput id="reset-email" name="email" placeholder="you@example.com" type="email" autoComplete="email" />
          <button className="rounded-lg bg-brand-primary px-4 py-2.5 font-medium text-white hover:bg-brand-hover">
            Send reset link
          </button>
        </div>
        <p className="mt-4 text-sm text-brand-muted">
          Remember your password?{" "}
          <Link className="font-medium text-brand-primary hover:underline" href="/auth">
            Sign in
          </Link>
        </p>
      </form>
    </section>
  );
}
