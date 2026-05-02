import dynamic from "next/dynamic";

// Three.js / React-Three-Fiber requires `window`, so render the studio
// client-side only. Keeps SSR fast and avoids hydration mismatches.
const DesignStudio = dynamic(
  () => import("../../components/Design/DesignStudio"),
  { ssr: false },
);

export const metadata = {
  title: "Pulsai Design Studio",
};

export default function DesignStudioPage() {
  return <DesignStudio />;
}
