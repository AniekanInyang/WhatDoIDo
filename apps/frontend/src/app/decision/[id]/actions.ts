"use server";

import { addDecisionMessage, renameDecision as renameDecisionApi } from "@/lib/api/decisions";
import { revalidatePath } from "next/cache";


export async function renameDecision(id: string, formData: FormData) {
  const title = String(formData.get("title") ?? "").trim();
  if (!title) return;

  await renameDecisionApi(id, title);
  revalidatePath(`/decision/${id}`);
  revalidatePath("/history");
}

export async function sendMessage(id: string, formData: FormData) {
  const content = String(formData.get("message") ?? "").trim();
  if (!content) return;

  await addDecisionMessage(id, content);
  revalidatePath(`/decision/${id}`);
}
