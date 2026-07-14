import type { Metadata } from "next";
import { Space_Grotesk } from "next/font/google";
import { AppShell } from "@/components/app-shell";
import { createClient } from "@/lib/supabase/server";
import "./globals.css";

const space = Space_Grotesk({ subsets: ["latin"], variable: "--font-space" });

export const metadata: Metadata = {
  title: "What Do I Do?",
  description: "Production-ready AI decision support UI",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  return (
    <html lang="en" className={space.variable}>
      <body>
        <AppShell userEmail={user?.email}>{children}</AppShell>
      </body>
    </html>
  );
}
