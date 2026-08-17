"use client";

import { useRouter } from "next/navigation";
import { ButtonHTMLAttributes } from "react";

export function HistoryBackButton() {
  const router = useRouter();
  return <button onClick={() => router.back()} className="pill rounded-lg px-3 py-2 text-sm font-medium">Back</button>;
}

export function ConfirmDeleteButton(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      onClick={(event) => {
        if (!window.confirm("Permanently delete this decision? This cannot be undone.")) {
          event.preventDefault();
        }
      }}
    />
  );
}
