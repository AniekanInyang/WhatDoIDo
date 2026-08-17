"use server";

import { deleteAccount as deleteAccountApi, updateProfile } from "@/lib/api/account";
import { createClient } from "@/lib/supabase/server";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

function value(formData: FormData, key: string) {
  return String(formData.get(key) ?? "").trim();
}

function settingsRedirect(message: string, type: "error" | "message" = "message"): never {
  redirect(`/settings?${type}=${encodeURIComponent(message)}`);
}

export async function changeDisplayName(formData: FormData) {
  const displayName = value(formData, "displayName");
  if (!displayName) settingsRedirect("Display name is required.", "error");
  await updateProfile(displayName);
  revalidatePath("/settings");
  settingsRedirect("Display name updated.");
}

export async function changeEmail(formData: FormData) {
  const email = value(formData, "email");
  const supabase = createClient();
  const { error } = await supabase.auth.updateUser({ email });
  if (error) settingsRedirect(error.message, "error");
  settingsRedirect("Email update requested. Check your inbox if confirmation is required.");
}

export async function changePassword(formData: FormData) {
  const currentPassword = value(formData, "currentPassword");
  const password = value(formData, "password");
  const confirmPassword = value(formData, "confirmPassword");
  if (password.length < 8) settingsRedirect("New password must be at least 8 characters.", "error");
  if (password !== confirmPassword) settingsRedirect("New passwords do not match.", "error");

  const supabase = createClient();
  const { error } = await supabase.auth.updateUser({
    password,
    current_password: currentPassword,
  });
  if (error) settingsRedirect(error.message, "error");
  settingsRedirect("Password updated.");
}

export async function signOutCurrentSession() {
  const supabase = createClient();
  await supabase.auth.signOut({ scope: "local" });
  redirect("/");
}

export async function signOutAllSessions() {
  const supabase = createClient();
  await supabase.auth.signOut({ scope: "global" });
  redirect("/");
}

export async function deleteAccount(formData: FormData) {
  const password = value(formData, "password");
  const confirmation = value(formData, "confirmation");
  if (confirmation !== "DELETE") settingsRedirect('Type "DELETE" to confirm.', "error");

  await deleteAccountApi(password, confirmation);
  const supabase = createClient();
  await supabase.auth.signOut({ scope: "local" });
  redirect("/auth?message=Your%20account%20and%20data%20have%20been%20deleted.");
}
