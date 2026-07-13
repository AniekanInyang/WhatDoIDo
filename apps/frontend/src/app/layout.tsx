import type { Metadata } from "next";
import { Space_Grotesk } from "next/font/google";
import { AppShell } from "@/components/app-shell";
import "./globals.css";

const space = Space_Grotesk({ subsets: ["latin"], variable: "--font-space" });

export const metadata: Metadata = {
  title: "WhatDoIDo",
  description: "Production-ready AI decision support UI",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={space.variable}>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
