import { getAccountExport } from "@/lib/api/account";

export async function GET() {
  const data = await getAccountExport();
  const date = new Date().toISOString().slice(0, 10);
  return new Response(JSON.stringify(data, null, 2), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Content-Disposition": `attachment; filename="whatdoido-export-${date}.json"`,
      "Cache-Control": "private, no-store",
    },
  });
}
