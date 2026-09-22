"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

type NavigationResult = { redirect_to: string };

export function LandingDecisionForm({
  action,
}: {
  action: (formData: FormData) => Promise<void | NavigationResult>;
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;

    const formData = new FormData(event.currentTarget);
    const message = String(formData.get("message") ?? "").trim();
    if (!message) return;

    setPending(true);
    setError("");

    try {
      const result = await action(formData);
      if (result?.redirect_to) {
        router.push(result.redirect_to);
        return;
      }
      setError("The decision could not be started. Please try again.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The decision could not be started. Please try again.");
    }

    setPending(false);
  }

  return (
    <form onSubmit={handleSubmit}>
      <label className="mt-4 block text-sm font-medium text-brand-text" htmlFor="decision">
        What are you trying to decide?
      </label>
      <textarea
        id="decision"
        name="message"
        className="field mt-2 min-h-32 w-full resize-none p-3 text-sm"
        placeholder="Example: Should I accept the startup offer or stay in my current role?"
        required
        maxLength={50000}
        disabled={pending}
      />

      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        {["Options", "Constraints", "Risks"].map((item) => (
          <div key={item} className="surface-panel p-3">
            <p className="text-[11px] uppercase tracking-[0.15em] text-brand-muted">{item}</p>
            <p className="mt-1 text-sm text-brand-text">Captured as you talk</p>
          </div>
        ))}
      </div>

      {error ? (
        <p className="mt-4 rounded-lg bg-brand-soft px-3 py-2 text-sm text-brand-text" role="alert">
          {error}
        </p>
      ) : null}

      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <button
          type="submit"
          disabled={pending}
          className="rounded-lg bg-brand-primary px-4 py-2.5 text-center text-sm font-medium text-white transition hover:bg-brand-hover disabled:cursor-wait disabled:opacity-60"
        >
          {pending ? "Starting…" : "Continue"}
        </button>
        <p className="self-center text-xs text-brand-muted">Start fresh now. Save history after signing in.</p>
      </div>
    </form>
  );
}
