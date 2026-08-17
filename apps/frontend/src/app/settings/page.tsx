import { PageHeader } from "@/components/page-header";
import { AuthInput } from "@/components/auth-input";
import { getAccount } from "@/lib/api/account";
import {
  changeDisplayName,
  changeEmail,
  changePassword,
  deleteAccount,
  signOutAllSessions,
  signOutCurrentSession,
} from "./actions";

type SettingsPageProps = { searchParams: { error?: string; message?: string } };

export default async function SettingsPage({ searchParams }: SettingsPageProps) {
  const account = await getAccount();

  return (
    <section>
      <PageHeader eyebrow="Settings" title="Account & Security" subtitle="Manage your identity, sessions, and data." />

      {(searchParams.error || searchParams.message) && (
        <p className={`mb-4 rounded-lg border p-3 text-sm ${searchParams.error ? "border-red-200 bg-red-50 text-red-700" : "border-brand-border bg-brand-soft text-brand-text"}`}>
          {searchParams.error ?? searchParams.message}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <article className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Profile</h3>
          <p className="mt-1 text-sm text-brand-muted">Signed in as {account.email}</p>
          <form action={changeDisplayName} className="mt-4 grid gap-2 text-sm">
            <label className="font-medium text-brand-text" htmlFor="displayName">Display name</label>
            <input id="displayName" name="displayName" defaultValue={account.profile.display_name} className="field p-3" required maxLength={100} />
            <button className="rounded-lg bg-brand-primary px-4 py-2.5 font-medium text-white hover:bg-brand-hover">Save display name</button>
          </form>
        </article>

        <article className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Email</h3>
          <form action={changeEmail} className="mt-4 grid gap-2 text-sm">
            <label className="font-medium text-brand-text" htmlFor="email">New email address</label>
            <input id="email" name="email" defaultValue={account.email ?? ""} className="field p-3" type="email" required autoComplete="email" />
            <button className="rounded-lg border border-brand-border bg-brand-soft px-4 py-2.5 font-medium text-brand-text hover:border-brand-accent">Update email</button>
          </form>
        </article>

        <article className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Password</h3>
          <form action={changePassword} className="mt-4 grid gap-2 text-sm">
            <AuthInput id="settings-current-password" name="currentPassword" type="password" placeholder="Current password" autoComplete="current-password" nextId="settings-new-password" />
            <AuthInput id="settings-new-password" name="password" type="password" placeholder="New password (8+ characters)" minLength={8} autoComplete="new-password" nextId="settings-confirm-password" />
            <AuthInput id="settings-confirm-password" name="confirmPassword" type="password" placeholder="Confirm new password" minLength={8} autoComplete="new-password" />
            <button className="rounded-lg border border-brand-border bg-brand-soft px-4 py-2.5 font-medium text-brand-text hover:border-brand-accent">Change password</button>
          </form>
        </article>

        <article className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Sessions</h3>
          <p className="mt-1 text-sm text-brand-muted">Choose whether to sign out this browser or every active session.</p>
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            <form action={signOutCurrentSession}><button className="w-full rounded-lg border border-brand-border bg-brand-soft px-4 py-2.5 text-sm font-medium text-brand-text hover:border-brand-accent">Sign out here</button></form>
            <form action={signOutAllSessions}><button className="w-full rounded-lg border border-brand-border bg-brand-soft px-4 py-2.5 text-sm font-medium text-brand-text hover:border-brand-accent">Sign out everywhere</button></form>
          </div>
        </article>

        <article className="surface-card p-5">
          <h3 className="text-base font-semibold text-brand-text">Download your data</h3>
          <p className="mt-1 text-sm leading-6 text-brand-muted">Download your profile, decisions, messages, options, evaluations, and recommendations as JSON.</p>
          <a href="/api/account/export" className="mt-4 inline-block rounded-lg border border-brand-border bg-brand-soft px-4 py-2.5 text-sm font-medium text-brand-text hover:border-brand-accent">Download JSON export</a>
        </article>

        <article className="surface-card border-red-200 p-5">
          <h3 className="text-base font-semibold text-red-700">Delete account</h3>
          <p className="mt-1 text-sm leading-6 text-brand-muted">Permanently deletes your account and all saved decisions. This cannot be undone.</p>
          <form action={deleteAccount} className="mt-4 grid gap-2 text-sm">
            <AuthInput id="delete-current-password" name="password" type="password" placeholder="Current password" autoComplete="current-password" nextId="delete-confirmation" />
            <input id="delete-confirmation" name="confirmation" className="field p-3" placeholder='Type "DELETE"' required autoComplete="off" />
            <button className="rounded-lg bg-red-700 px-4 py-2.5 font-medium text-white hover:bg-red-800">Permanently delete account</button>
          </form>
        </article>
      </div>
    </section>
  );
}
