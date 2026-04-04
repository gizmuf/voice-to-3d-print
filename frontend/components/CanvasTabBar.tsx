"use client";

export type CanvasTab = "2d" | "3d" | "compare";

type TabOption = {
  id: CanvasTab;
  label: string;
};

type Props = {
  tabs: TabOption[];
  activeTab: CanvasTab;
  onChange: (tab: CanvasTab) => void;
};

export default function CanvasTabBar({ tabs, activeTab, onChange }: Props) {
  return (
    <div className="canvas-tab-bar" role="tablist" aria-label="Canvas view">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          className={`canvas-tab ${activeTab === tab.id ? "active" : ""}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
