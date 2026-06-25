import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "Novel Forge Admin",
  description: "Novel Forge industrial operations console"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
