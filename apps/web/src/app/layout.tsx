import type { Metadata } from "next";
import "./globals.css";
import LocaleProvider from "@/components/locale-provider";

export const metadata: Metadata = {
  title: "CaseQuarry — Evidence workspace",
  description:
    "Private matter management, evidence search, source preservation and human review.",
  icons: { icon: "/favicon.svg" },
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <LocaleProvider>{children}</LocaleProvider>
      </body>
    </html>
  );
}
