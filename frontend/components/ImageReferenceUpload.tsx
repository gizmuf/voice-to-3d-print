"use client";

import type { ChangeEvent } from "react";

type Props = {
  disabled?: boolean;
  imagePreviewUrl: string | null;
  onChange: (file: File | null) => void;
  onRemove: () => void;
};

export default function ImageReferenceUpload({
  disabled,
  imagePreviewUrl,
  onChange,
  onRemove,
}: Props) {
  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    onChange(event.target.files?.[0] ?? null);
  };

  return (
    <div className="image-reference-upload">
      <label className="field-row">
        <span>Reference image</span>
        <input type="file" accept="image/*" onChange={handleFileChange} disabled={disabled} />
      </label>
      {imagePreviewUrl ? (
        <div className="image-reference-preview">
          <img src={imagePreviewUrl} alt="Reference" />
          <button type="button" className="mode-chip subtle-chip" onClick={onRemove}>
            Remove image
          </button>
        </div>
      ) : null}
    </div>
  );
}
