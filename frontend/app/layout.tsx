import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BBMR 策略链路",
  description: "本地策略状态与归档流水线展示。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
