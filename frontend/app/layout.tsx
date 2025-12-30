import type { Metadata } from "next";
import { Fraunces, Space_Grotesk } from "next/font/google";
import "../styles/globals.css";

const space = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-body"
});

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-display"
});

export const metadata: Metadata = {
  title: "Voice to 3D Print",
  description: "Serverless voice-to-3D-print prototype"
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${space.variable} ${fraunces.variable}`}>
        {children}
      </body>
    </html>
  );
}
