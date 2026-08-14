import type { Metadata } from "next";
import { Fraunces, Space_Grotesk } from "next/font/google";
import "../styles/globals.css";
import GoogleAuthGate from "../components/Auth/GoogleAuthGate";

const space = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-body"
});

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-display"
});

export const metadata: Metadata = {
  title: "Pulsai 3D",
  description: "Conversation-first parametric CAD and 3D-print preparation."
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pl">
      <body className={`${space.variable} ${fraunces.variable}`}>
        <GoogleAuthGate>{children}</GoogleAuthGate>
      </body>
    </html>
  );
}
