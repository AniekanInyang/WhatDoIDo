"use server";

import { createDecision } from "@/lib/api/decisions";
import { redirect } from "next/navigation";


export async function startDecision(formData: FormData) {
  const prompt = String(formData.get("message") ?? "").trim();
  if (!prompt) return;

  const decision = await createDecision({ prompt });
  redirect(`/decision/${decision.id}`);
}
