"use server";

import {
  addDecisionMessage,
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
  await retryDecisionWorkflow(id);
  revalidatePath(`/decision/${id}`);
}
