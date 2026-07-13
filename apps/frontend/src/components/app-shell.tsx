"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PropsWithChildren } from "react";

export function AppShell({ children }: PropsWithChildren) {
  const pathname = usePathname();
  const isLanding = pathname === "/";
  const isConversation = pathname === "/decision/conversation";

  const nav = [
    { href: "/", label: "Home" },
    { href: "/decision/conversation", label: "New" },
    { href: "/history", label: "History" },
    { href: "/insights", label: "Insights" },
    { href: "/settings", label: "Settings" },
  ];

  return (
    <div className="min-h-screen px-4 py-6 md:px-6 lg:px-8">
      <header className="entry surface-card mx-auto mb-4 flex w-full max-w-6xl flex-col gap-4 p-4 md:flex-row md:items-center md:justify-between">
        <div className="text-center md:text-left">
          <p className="text-[11px] uppercase tracking-[0.18em] text-brand-muted">Decision Intelligence</p>
          <h1 className="headline mt-1 text-xl font-semibold text-brand-text">WhatDoIDo</h1>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-2 md:justify-end">
          {!isLanding &&
            nav.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-full px-3 py-1.5 text-xs transition ${
                    active
                      ? "bg-brand-primary text-white"
                      : "pill hover:border-brand-accent hover:text-brand-text"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}

          {(isLanding || !isConversation) && (
            <Link
              href="/decision/conversation"
              className="rounded-full bg-brand-primary px-3.5 py-1.5 text-xs font-medium text-white transition hover:bg-brand-hover"
            >
              Start
            </Link>
          )}

          {isLanding && (
            <Link
              href="/auth"
              className="pill rounded-full px-3.5 py-1.5 text-xs transition hover:text-brand-text"
            >
              Sign In
            </Link>
          )}
          {!isLanding && isConversation && (
            <Link href="/" className="pill rounded-full px-3.5 py-1.5 text-xs transition hover:text-brand-text">
              Home
            </Link>
          )}
        </div>
      </header>

      <main className="entry mx-auto w-full max-w-6xl pb-8">{children}</main>
    </div>
  );
}
