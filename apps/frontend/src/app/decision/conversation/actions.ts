"use server";

import { createDecision } from "@/lib/api/decisions";


export async function startDecision(formData: FormData) {
  const prompt = String(formData.get("message") ?? "").trim();
  if (!prompt) return;

  const decision = await createDecision({ prompt });
  return { redirect_to: `/decision/${decision.id}` };
}
