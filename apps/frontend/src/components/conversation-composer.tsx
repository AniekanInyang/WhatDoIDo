"use client";

import { FormEvent, KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type ConversationMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
};

type ConversationTurn = {
  user_message: ConversationMessage;
  assistant_message: ConversationMessage;
};

type NavigationResult = { redirect_to: string };


function SendButton({ pending }: { pending: boolean }) {
  return (
    <button
      disabled={pending}
      className="rounded-lg bg-brand-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-hover disabled:cursor-wait disabled:opacity-60"
    >
      Send
    </button>
  );
}


export function ConversationComposer({
  action,
  messages,
  showEmptyState = false,
  awaitingReply = false,
  readOnly = false,
  readOnlyMessage = "This decision is complete. You can still rename it, but its conversation and options are read-only.",
}: {
  action: (formData: FormData) => void | ConversationTurn | NavigationResult | Promise<void | ConversationTurn | NavigationResult>;
  messages?: ConversationMessage[];
  showEmptyState?: boolean;
  awaitingReply?: boolean;
  readOnly?: boolean;
  readOnlyMessage?: string;
}) {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const conversationRef = useRef<HTMLDivElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const [pending, setPending] = useState(false);
  const [optimisticMessage, setOptimisticMessage] = useState("");
  const [displayMessages, setDisplayMessages] = useState<ConversationMessage[]>(messages ?? []);

  useEffect(() => {
    if (!awaitingReply) return;
    const interval = window.setInterval(() => router.refresh(), 1000);
    return () => window.clearInterval(interval);
  }, [awaitingReply, router]);

  useEffect(() => {
    if (!messages) return;
    setDisplayMessages((current) => {
      const incomingIds = new Set(messages.map((message) => message.id));
      const localOnly = current.filter((message) => !incomingIds.has(message.id));
      return [...messages, ...localOnly];
    });
  }, [messages]);

  useLayoutEffect(() => {
    if (!displayMessages.length && !pending) return;
    const conversation = conversationRef.current;
    if (!conversation || !endRef.current) return;
    conversation.scrollTo({
      top: conversation.scrollHeight,
      behavior: pending ? "smooth" : "auto",
    });
  }, [displayMessages.length, pending]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      formRef.current?.requestSubmit();
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;

    const form = event.currentTarget;
    const formData = new FormData(form);
    const message = String(formData.get("message") ?? "").trim();
    if (!message) return;

    setOptimisticMessage(message);
    setPending(true);
    form.reset();

    let navigating = false;
    try {
      const turn = await action(formData);
      if (turn && typeof turn === "object" && "redirect_to" in turn) {
        navigating = true;
        router.push(turn.redirect_to);
        return;
      }
      if (turn && typeof turn === "object" && "user_message" in turn) {
        setDisplayMessages((current) => {
          const withoutTurn = current.filter(
            (item) => item.id !== turn.user_message.id && item.id !== turn.assistant_message.id,
          );
          return [...withoutTurn, turn.user_message, turn.assistant_message];
        });
      }
    } finally {
      if (!navigating) {
        setOptimisticMessage("");
        setPending(false);
      }
    }
  }

  return (
    <div className="mt-3">
      {(messages || showEmptyState) && (
        <div ref={conversationRef} className="h-[52vh] overflow-y-auto pr-2">
          <div className="flex flex-col gap-3">
            {showEmptyState && !displayMessages.length && !pending && (
              <div className="flex min-h-[44vh] items-center justify-center rounded-lg border border-dashed border-brand-border bg-brand-soft/50 p-6 text-center">
                <div className="max-w-md">
                  <p className="text-base font-semibold text-brand-text">What decision do you need help with?</p>
                  <p className="mt-2 text-sm leading-6 text-brand-muted">
                    Describe the choice in plain language. Once you send the first message, this space becomes the working conversation.
                  </p>
                </div>
              </div>
            )}
            {displayMessages.map((message) => (
              <div
                key={message.id}
                className={`max-w-[85%] rounded-xl px-4 py-3 ${
                  message.role === "user"
                    ? "ml-auto bg-brand-primary text-white"
                    : "mr-auto border border-brand-border bg-brand-soft text-brand-text"
                }`}
              >
                <p className="text-sm leading-6">{message.content}</p>
              </div>
            ))}
            {pending && (
              <div className="ml-auto max-w-[85%] rounded-xl bg-brand-primary px-4 py-3 text-white">
                <p className="text-sm leading-6">{optimisticMessage}</p>
              </div>
            )}
            {(pending || awaitingReply) && (
              <>
                <div className="mr-auto rounded-xl border border-brand-border bg-brand-soft px-4 py-3" role="status" aria-live="polite">
                  <p className="text-sm leading-6 text-brand-muted">Thinking…</p>
                </div>
              </>
            )}
            <div ref={endRef} className="h-px shrink-0" aria-hidden="true" />
          </div>
        </div>
      )}
      {!readOnly ? <form ref={formRef} onSubmit={handleSubmit} className="flex items-end gap-2">
        <textarea
          name="message"
          className="field min-h-12 min-w-0 flex-1 resize-none p-3 text-sm"
          placeholder="Type your message…"
          rows={1}
          required
          maxLength={50000}
          disabled={pending || awaitingReply}
          onKeyDown={handleKeyDown}
        />
        <SendButton pending={pending || awaitingReply} />
      </form> : (
        <p className="rounded-lg bg-brand-soft px-3 py-2 text-xs text-brand-muted">
          {readOnlyMessage}
        </p>
      )}
    </div>
  );
}
