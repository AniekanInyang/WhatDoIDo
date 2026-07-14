import { updatePassword } from "../actions";
import { PageHeader } from "@/components/page-header";
import { AuthInput } from "@/components/auth-input";

export default function UpdatePasswordPage({ searchParams }: { searchParams: { error?: string } }) {
  return (
    <section className="mx-auto max-w-xl">
      <PageHeader eyebrow="Account" title="Choose a new password" subtitle="Use at least eight characters." />
      <form action={updatePassword} className="surface-card grid gap-3 p-5 text-sm">
        {searchParams.error && <p className="rounded-lg bg-red-50 p-3 text-red-700">{searchParams.error}</p>}
        <label className="font-medium text-brand-text" htmlFor="password">New password</label>
        <AuthInput id="password" name="password" type="password" minLength={8} autoComplete="new-password" nextId="confirmPassword" />
        <label className="font-medium text-brand-text" htmlFor="confirmPassword">Confirm password</label>
        <AuthInput id="confirmPassword" name="confirmPassword" type="password" minLength={8} autoComplete="new-password" />
        <button className="rounded-lg bg-brand-primary px-4 py-2.5 font-medium text-white hover:bg-brand-hover">Update password</button>
      </form>
    </section>
  );
}
