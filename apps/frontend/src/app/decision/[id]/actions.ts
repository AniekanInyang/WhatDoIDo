"use server";

import {
  addDecisionMessage,
  completeDecision as completeDecisionApi,
  createDecisionOption as createOptionApi,
  deleteDecisionOption as deleteOptionApi,
  renameDecision as renameDecisionApi,
  updateDecisionOption as updateOptionApi,
  reviewDecisionOption,
  reviewDecisionBriefItem,
  resolveDecisionContradiction,
  retryDecisionWorkflow,
} from "@/lib/api/decisions";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";


export async function renameDecision(id: string, formData: FormData) {
  const title = String(formData.get("title") ?? "").trim();
  if (!title) return;

  await renameDecisionApi(id, title);
  revalidatePath(`/decision/${id}`);
  revalidatePath("/history");
}

export async function completeDecision(id: string) {
  await completeDecisionApi(id);
  revalidatePath(`/decision/${id}`);
  revalidatePath("/history");
}

export async function sendMessage(id: string, formData: FormData) {
  const content = String(formData.get("message") ?? "").trim();
  if (!content) return;

  const turn = await addDecisionMessage(id, content);
  revalidatePath(`/decision/${id}`);
  return turn;
}

export async function createOption(id: string, formData: FormData) {
  const title = String(formData.get("title") ?? "").trim();
  const description = String(formData.get("description") ?? "").trim();
  if (!title) return;
  await createOptionApi(id, { title, description: description || undefined });
  revalidatePath(`/decision/${id}`);
}

export async function updateOption(id: string, optionId: string, formData: FormData) {
  const title = String(formData.get("title") ?? "").trim();
  const description = String(formData.get("description") ?? "").trim();
  if (!title) return;
  await updateOptionApi(id, optionId, { title, description: description || undefined });
  revalidatePath(`/decision/${id}`);
}

export async function deleteOption(id: string, optionId: string) {
  await deleteOptionApi(id, optionId);
  revalidatePath(`/decision/${id}`);
}

export async function reviewOption(id: string, optionId: string, status: "confirmed" | "rejected") {
  await reviewDecisionOption(id, optionId, status);
  revalidatePath(`/decision/${id}`);
}

export async function reviewBriefItem(
  id: string,
  collection: string,
  itemId: string,
  status: "confirmed" | "rejected",
  formData?: FormData,
) {
  const replacement = String(formData?.get("replacement") ?? "").trim();
  await reviewDecisionBriefItem(id, {
    collection,
    item_id: itemId,
    status,
    replacement: replacement || undefined,
  });
  revalidatePath(`/decision/${id}`);
}

export async function resolveContradiction(
  id: string,
  contradictionId: string,
  resolution: "previous" | "new",
) {
  await resolveDecisionContradiction(id, { contradiction_id: contradictionId, resolution });
  revalidatePath(`/decision/${id}`);
}

export async function retryWorkflow(id: string) {
  let retryError: string | null = null;
  try {
    await retryDecisionWorkflow(id);
  } catch (error) {
    retryError = error instanceof Error ? error.message : "The workflow could not be retried.";
  }
  if (retryError) {
    redirect(`/decision/${id}?retry_error=${encodeURIComponent(retryError)}`);
  }
  revalidatePath(`/decision/${id}`);
}
