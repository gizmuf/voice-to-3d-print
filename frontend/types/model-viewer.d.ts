declare namespace JSX {
  interface IntrinsicElements {
    "model-viewer": React.DetailedHTMLProps<
      React.HTMLAttributes<HTMLElement>,
      HTMLElement
    > & {
      src?: string;
      alt?: string;
      poster?: string;
      "camera-controls"?: boolean;
      "auto-rotate"?: boolean;
      "shadow-intensity"?: string | number;
      exposure?: string | number;
      ar?: boolean;
    };
  }
}
