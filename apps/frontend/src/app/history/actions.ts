"use server";

import {
  createCollection as createCollectionApi,
  deleteCollection as deleteCollectionApi,
  moveDecision as moveDecisionApi,
  permanentlyDeleteDecision as permanentlyDeleteDecisionApi,
  renameCollection as renameCollectionApi,
  restoreDecision as restoreDecisionApi,
  trashDecision as trashDecisionApi,
} from "@/lib/api/decisions";
import { revalidatePath } from "next/cache";

const field = (formData: FormData, name: string) => String(formData.get(name) ?? "").trim();

export async function createCollection(formData: FormData) {
  const name = field(formData, "name");
  if (!name) return;
  await createCollectionApi(name);
  revalidatePath("/history");
}

export async function renameCollection(formData: FormData) {
  const id = field(formData, "id");
  const name = field(formData, "name");
  if (!id || !name) return;
  await renameCollectionApi(id, name);
  revalidatePath("/history");
}

export async function deleteCollection(formData: FormData) {
  const id = field(formData, "id");
  if (!id) return;
  await deleteCollectionApi(id);
  revalidatePath("/history");
}

export async function moveDecision(formData: FormData) {
  const decisionId = field(formData, "decisionId");
  const collectionId = field(formData, "collectionId") || null;
  if (!decisionId) return;
  await moveDecisionApi(decisionId, collectionId);
  revalidatePath("/history");
}

export async function trashDecision(formData: FormData) {
  const id = field(formData, "id");
  if (!id) return;
  await trashDecisionApi(id);
  revalidatePath("/history");
}

export async function restoreDecision(formData: FormData) {
  const id = field(formData, "id");
  if (!id) return;
  await restoreDecisionApi(id);
  revalidatePath("/history");
}

export async function permanentlyDeleteDecision(formData: FormData) {
  const id = field(formData, "id");
  if (!id) return;
  await permanentlyDeleteDecisionApi(id);
  revalidatePath("/history");
}
