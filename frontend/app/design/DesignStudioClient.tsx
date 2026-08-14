"use client";

import dynamic from "next/dynamic";

// Three.js / React-Three-Fiber requires `window`, so keep the dynamic import
// in a Client Component while the route remains a Server Component that can
// export metadata.
const DesignStudio = dynamic(
  () => import("../../components/Design/DesignStudio"),
  { ssr: false },
);

export default function DesignStudioClient() {
  return <DesignStudio />;
}
