import { authenticatedFetch } from "./decisions";

export type AccountOverview = {
  id: string;
  email: string | null;
  created_at: string | null;
  last_sign_in_at: string | null;
  profile: {
    id: string;
    display_name: string;
    created_at: string;
    updated_at: string;
  };
};

export function getAccount() {
  return authenticatedFetch<AccountOverview>("/account", undefined, "/settings");
}

export function updateProfile(displayName: string) {
  return authenticatedFetch<AccountOverview["profile"]>(
    "/account/profile",
    { method: "PATCH", body: JSON.stringify({ display_name: displayName }) },
    "/settings",
  );
}

export function getAccountExport() {
  return authenticatedFetch<Record<string, unknown>>("/account/export", undefined, "/settings");
}

export function deleteAccount(password: string, confirmation: string) {
  return authenticatedFetch<void>(
    "/account",
    { method: "DELETE", body: JSON.stringify({ password, confirmation }) },
    "/settings",
  );
}
