import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";

export type DecisionSummary = {
  id: string;
  title: string;
  prompt: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type DecisionOption = {
  id: string;
  title: string;
  description: string | null;
  position: number;
  evaluation: Record<string, unknown>;
};

export type DecisionMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
};

export type Evaluation = {
  id: string;
  summary: string;
  confidence: number | null;
  risk_level: string | null;
  created_at: string;
};

export type DecisionDetail = DecisionSummary & {
  decision_brief: Record<string, unknown>;
  recommendation: Record<string, unknown> | null;
  options: DecisionOption[];
  messages: DecisionMessage[];
  evaluations: Evaluation[];
};

function apiUrl() {
  return process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

async function authenticatedFetch<T>(path: string, init?: RequestInit, next = "/history"): Promise<T> {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect(`/auth?next=${encodeURIComponent(next)}`);

  const { data: { session } } = await supabase.auth.getSession();
  if (!session?.access_token) redirect("/auth");

  const response = await fetch(`${apiUrl()}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.access_token}`,
      ...init?.headers,
    },
  });

  if (response.status === 401) redirect("/auth");
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? "The decision service request failed.");
  }
  return response.json() as Promise<T>;
}

export function listDecisions() {
  return authenticatedFetch<DecisionSummary[]>("/decisions");
}

export function getDecision(id: string) {
  return authenticatedFetch<DecisionDetail>(`/decisions/${encodeURIComponent(id)}`);
}

export function createDecision(values: { prompt: string }) {
  return authenticatedFetch<DecisionSummary>("/decisions", {
    method: "POST",
    body: JSON.stringify(values),
  }, "/decision/conversation");
}

export function addDecisionMessage(id: string, content: string) {
  return authenticatedFetch<{ user_message: DecisionMessage; assistant_message: DecisionMessage }>(
    `/decisions/${encodeURIComponent(id)}/messages`,
    { method: "POST", body: JSON.stringify({ content }) },
    `/decision/${id}`,
  );
}

export function renameDecision(id: string, title: string) {
  return authenticatedFetch<DecisionSummary>(`/decisions/${encodeURIComponent(id)}/title`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}
