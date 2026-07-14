"use server";

import { createClient } from "@/lib/supabase/server";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

function value(formData: FormData, key: string) {
  return String(formData.get(key) ?? "").trim();
}

function authRedirect(message: string, type: "error" | "message" = "error") {
  redirect(`/auth?${type}=${encodeURIComponent(message)}`);
}

export async function signIn(formData: FormData) {
  const email = value(formData, "email");
  const password = value(formData, "password");
  const next = value(formData, "next");
  const supabase = createClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });

  if (error) authRedirect(error.message);
  redirect(next.startsWith("/") && !next.startsWith("//") ? next : "/history");
}

export async function signUp(formData: FormData) {
  const name = value(formData, "name");
  const email = value(formData, "email");
  const password = value(formData, "password");
  const supabase = createClient();
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: { data: { display_name: name } },
  });

  if (error) authRedirect(error.message);
  if (!data.session) {
    authRedirect("Check your email to confirm your account.", "message");
  }
  redirect("/history");
}

export async function signOut() {
  const supabase = createClient();
  await supabase.auth.signOut();
  redirect("/");
}

export async function requestPasswordReset(formData: FormData) {
  const email = value(formData, "email");
  const origin = headers().get("origin");
  const supabase = createClient();
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${origin ?? "http://localhost:3000"}/auth/callback?next=/auth/update-password`,
  });

  if (error) authRedirect(error.message);
  authRedirect("If an account exists, a password reset link has been sent.", "message");
}

export async function updatePassword(formData: FormData) {
  const password = value(formData, "password");
  const confirmPassword = value(formData, "confirmPassword");
  if (password.length < 8) {
    redirect("/auth/update-password?error=Password%20must%20be%20at%20least%208%20characters.");
  }
  if (password !== confirmPassword) {
    redirect("/auth/update-password?error=Passwords%20do%20not%20match.");
  }

  const supabase = createClient();
  const { error } = await supabase.auth.updateUser({ password });
  if (error) redirect(`/auth/update-password?error=${encodeURIComponent(error.message)}`);
  redirect("/settings?message=Password updated");
}
