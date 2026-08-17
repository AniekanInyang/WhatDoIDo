"use client";

import { FormEvent, KeyboardEvent, useLayoutEffect, useRef, useState } from "react";

type ConversationMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
};


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
}: {
  action: (formData: FormData) => void | Promise<void>;
  messages?: ConversationMessage[];
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const conversationRef = useRef<HTMLDivElement | null>(null);
  const newestRef = useRef<HTMLDivElement | null>(null);
  const latestMessageRef = useRef<HTMLDivElement | null>(null);
  const [pending, setPending] = useState(false);
  const [optimisticMessage, setOptimisticMessage] = useState("");
  const latestExchangeStart = messages
    ? Math.max(0, messages.length - (pending ? 1 : 2))
    : 0;

  useLayoutEffect(() => {
    if (!messages?.length && !pending) return;
    const conversation = conversationRef.current;
    const exchangeStart = newestRef.current;
    const latestMessage = latestMessageRef.current;
    if (!conversation || !exchangeStart || !latestMessage) return;

    const conversationRect = conversation.getBoundingClientRect();
    const exchangeRect = exchangeStart.getBoundingClientRect();
    const latestRect = latestMessage.getBoundingClientRect();
    const exchangeTop = conversation.scrollTop + exchangeRect.top - conversationRect.top;
    const latestBottom = conversation.scrollTop + latestRect.bottom - conversationRect.top;
    const exchangeHeight = latestBottom - exchangeTop;
    if (exchangeHeight > conversation.clientHeight) {
      conversation.scrollTo({
        top: latestBottom - conversation.clientHeight + 12,
        behavior: "smooth",
      });
      return;
    }

    conversation.scrollTo({ top: exchangeTop, behavior: "smooth" });
  }, [messages?.length, pending]);

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

    try {
      await action(formData);
    } finally {
      setOptimisticMessage("");
      setPending(false);
    }
  }

  return (
    <div className="mt-3">
      {messages && (
        <div ref={conversationRef} className="h-[52vh] overflow-y-auto pr-2">
          <div className="flex flex-col gap-3">
            {messages.map((message, index) => (
              <div
                key={message.id}
                ref={(node) => {
                  if (index === latestExchangeStart) newestRef.current = node;
                  if (index === messages.length - 1 && !pending) latestMessageRef.current = node;
                }}
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
              <>
                <div className="ml-auto max-w-[85%] rounded-xl bg-brand-primary px-4 py-3 text-white">
                  <p className="text-sm leading-6">{optimisticMessage}</p>
                </div>
                <div ref={latestMessageRef} className="mr-auto px-1" role="status" aria-live="polite">
                  <p className="text-xs italic leading-5 text-brand-muted">Thinking…</p>
                </div>
              </>
            )}
            <div className="h-[38vh] shrink-0" aria-hidden="true" />
          </div>
        </div>
      )}
      {!messages && pending && (
        <div className="mb-3 flex flex-col gap-3">
          <div className="ml-auto max-w-[85%] rounded-xl bg-brand-primary px-4 py-3 text-white">
            <p className="text-sm leading-6">{optimisticMessage}</p>
          </div>
          <div className="mr-auto px-1" role="status" aria-live="polite">
            <p className="text-xs italic leading-5 text-brand-muted">Thinking…</p>
          </div>
        </div>
      )}
      <form ref={formRef} onSubmit={handleSubmit} className="flex items-end gap-2">
        <textarea
          name="message"
          className="field min-h-12 min-w-0 flex-1 resize-none p-3 text-sm"
          placeholder="Type your message…"
          rows={1}
          required
          maxLength={50000}
          disabled={pending}
          onKeyDown={handleKeyDown}
        />
        <SendButton pending={pending} />
      </form>
    </div>
  );
}
