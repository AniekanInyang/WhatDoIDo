"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ChangeEvent, useEffect, useState } from "react";

export function HistorySearch({ initialValue }: { initialValue: string }) {
  const [value, setValue] = useState(initialValue);
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      const params = new URLSearchParams(searchParams.toString());
      value.trim() ? params.set("q", value.trim()) : params.delete("q");
      params.delete("cursor");
      router.replace(`${pathname}?${params.toString()}`);
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [pathname, router, searchParams, value]);

  return (
    <input
      value={value}
      onChange={(event: ChangeEvent<HTMLInputElement>) => setValue(event.target.value)}
      className="field w-full p-3 text-sm"
      placeholder="Search titles and original decision prompts…"
      aria-label="Search decisions"
    />
  );
}
