import Link from "next/link";
import { AuthInput } from "@/components/auth-input";
import { PageHeader } from "@/components/page-header";
import { signUp } from "../actions";

type SignUpPageProps = { searchParams: { error?: string } };

export default function SignUpPage({ searchParams }: SignUpPageProps) {
  return (
    <section className="mx-auto max-w-2xl">
      <PageHeader
        eyebrow="Auth"
        title="Create account"
        subtitle="Create an account to save and revisit your decisions."
      />

      {searchParams.error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {searchParams.error}
        </p>
      )}

      <form action={signUp} className="surface-card p-5">
        <div className="grid gap-2 text-sm">
          <AuthInput id="sign-up-name" name="name" placeholder="Name" type="text" autoComplete="name" nextId="sign-up-email" />
          <AuthInput id="sign-up-email" name="email" placeholder="Email" type="email" autoComplete="email" nextId="sign-up-password" />
          <AuthInput id="sign-up-password" name="password" placeholder="Password (8+ characters)" type="password" minLength={8} autoComplete="new-password" />
          <button className="rounded-lg bg-brand-primary px-4 py-2.5 font-medium text-white hover:bg-brand-hover">
            Create account
          </button>
        </div>
        <p className="mt-4 text-sm text-brand-muted">
          Already have an account?{" "}
          <Link className="font-medium text-brand-primary hover:underline" href="/auth">
            Sign in
          </Link>
        </p>
      </form>
    </section>
  );
}
