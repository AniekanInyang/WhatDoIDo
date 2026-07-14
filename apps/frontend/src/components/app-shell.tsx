"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PropsWithChildren } from "react";
import { signOut } from "@/app/auth/actions";

type AppShellProps = PropsWithChildren<{ userEmail?: string }>;

export function AppShell({ children, userEmail }: AppShellProps) {
  const pathname = usePathname();
  const isLanding = pathname === "/";
  const isConversation = pathname === "/decision/conversation";
  const isAuth = pathname === "/auth";
  const showPrimaryNav = !isLanding && !isAuth;
  const showStart = (isLanding || !isConversation) && !isAuth;

  const nav = [
    { href: "/", label: "Home", requiresAuth: false },
    { href: "/decision/conversation", label: "New", requiresAuth: false },
    { href: "/history", label: "History", requiresAuth: true },
    { href: "/insights", label: "Insights", requiresAuth: true },
    { href: "/settings", label: "Settings", requiresAuth: true },
  ];

  return (
    <div className="min-h-screen px-3 py-4 sm:px-4 md:px-6 lg:px-8">
      <header className="entry surface-card mx-auto mb-5 flex w-full max-w-6xl flex-col gap-4 p-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="headline text-xl font-semibold text-brand-text">What Do I Do?</h1>
        </div>
        <nav className="flex w-full items-center gap-2 overflow-x-auto pb-1 md:w-auto md:flex-wrap md:justify-end md:overflow-visible md:pb-0">
          {showPrimaryNav &&
            nav.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.requiresAuth && !userEmail ? `/auth?next=${item.href}` : item.href}
                  className={`shrink-0 rounded-lg px-3 py-2 text-xs font-medium transition ${
                    active
                      ? "bg-brand-primary text-white"
                      : "pill hover:border-brand-accent hover:text-brand-text"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}

          {showStart && (
            <Link
              href="/decision/conversation"
              className="shrink-0 rounded-lg bg-brand-primary px-3.5 py-2 text-xs font-medium text-white transition hover:bg-brand-hover"
            >
              Start
            </Link>
          )}

          {isLanding && (
            <Link
              href="/auth"
              className="pill shrink-0 rounded-lg px-3.5 py-2 text-xs font-medium transition hover:text-brand-text"
            >
              View History
            </Link>
          )}
          {isAuth && (
            <Link href="/" className="pill shrink-0 rounded-lg px-3.5 py-2 text-xs font-medium transition hover:text-brand-text">
              Home
            </Link>
          )}
          {userEmail && !isAuth && (
            <form action={signOut} className="shrink-0">
              <button className="pill rounded-lg px-3.5 py-2 text-xs font-medium transition hover:text-brand-text" title={userEmail}>
                Sign out
              </button>
            </form>
          )}
        </nav>
      </header>

      <main className="entry mx-auto w-full max-w-6xl pb-8">{children}</main>
    </div>
  );
}
