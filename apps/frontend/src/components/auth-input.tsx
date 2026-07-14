"use client";

import { KeyboardEvent, useState } from "react";

type AuthInputProps = {
  id: string;
  name: string;
  type: "text" | "email" | "password";
  placeholder?: string;
  autoComplete?: string;
  minLength?: number;
  nextId?: string;
  className?: string;
};

export function AuthInput({
  id,
  name,
  type,
  placeholder,
  autoComplete,
  minLength,
  nextId,
  className = "field p-3",
}: AuthInputProps) {
  const [showPassword, setShowPassword] = useState(false);
  const isPassword = type === "password";

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" || !nextId) return;
    event.preventDefault();
    document.getElementById(nextId)?.focus();
  }

  const input = (
    <input
      id={id}
      name={name}
      className={`${className} ${isPassword ? "w-full pr-12" : ""}`}
      placeholder={placeholder}
      type={isPassword && showPassword ? "text" : type}
      required
      minLength={minLength}
      autoComplete={autoComplete}
      onKeyDown={handleKeyDown}
    />
  );

  if (!isPassword) return input;

  return (
    <div className="relative">
      {input}
      <button
        type="button"
        className="absolute inset-y-0 right-0 flex w-12 items-center justify-center text-brand-muted transition hover:text-brand-text"
        onClick={() => setShowPassword((visible) => !visible)}
        aria-label={showPassword ? "Hide password" : "Show password"}
        aria-pressed={showPassword}
      >
        {showPassword ? (
          <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5 fill-none stroke-current" strokeWidth="1.8">
            <path d="m3 3 18 18M10.6 10.7a2 2 0 0 0 2.7 2.7M9.9 4.3A10.8 10.8 0 0 1 12 4c5.5 0 9 5.5 9 5.5a15.6 15.6 0 0 1-2.3 2.8M6.2 6.2C4.1 7.6 3 9.5 3 9.5S6.5 15 12 15c1 0 2-.2 2.8-.5" />
          </svg>
        ) : (
          <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5 fill-none stroke-current" strokeWidth="1.8">
            <path d="M3 12s3.5-5.5 9-5.5 9 5.5 9 5.5-3.5 5.5-9 5.5S3 12 3 12Z" />
            <circle cx="12" cy="12" r="2.5" />
          </svg>
        )}
      </button>
    </div>
  );
}
