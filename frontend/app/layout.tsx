import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Home KTV",
  description: "家庭 KTV 系統",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-TW">
      <body>{children}</body>
    </html>
  );
}
