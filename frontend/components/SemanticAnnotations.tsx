"use client";

import { createElement } from "react";
import { Html } from "@react-three/drei";

import type { SemanticAnnotation } from "../lib/perforated-disc-geometry";

type Props = {
  items: SemanticAnnotation[];
};

export default function SemanticAnnotations({ items }: Props) {
  return (
    <>
      {items.map((item) => (
        createElement(
          "group",
          {
            key: item.id,
            position: [item.point.x, item.point.y, item.point.z],
          },
          createElement(
            Html,
            { distanceFactor: 16, center: true },
            createElement("div", { className: "semantic-annotation" }, item.label)
          )
        )
      ))}
    </>
  );
}
