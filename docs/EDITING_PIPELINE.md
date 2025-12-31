# Future: Multi-step 3D Editing Pipeline

## Goal
Allow users to iteratively refine a 3D model with multiple prompts until satisfied, then save a final version while preserving history.

## Core Challenges
- Most 3D generators are stateless: a new prompt often ignores prior geometry.
- Few providers offer true model-to-model editing or refinement.
- Consistency requires keeping a model "anchor" across revisions.

## Proposed Design (Future)
- Treat each edit as a new **revision** under a single **project**.
- Store all revisions in Firestore:
  - `project_id`, `revision_id`, `parent_revision_id`
  - prompt, provider, status, artifact URLs, timestamps
- Keep the "current model" as the latest revision.

## Possible Approaches
1) **Native model editing (ideal)**
   - Use provider features if available (model-to-model refine).
   - Input: previous GLB + edit prompt.
   - Output: new GLB tied to same project.

2) **Prompt-only re-generation (fallback)**
   - Rebuild model from a refined prompt.
   - Store prior prompt + deltas for continuity.
   - Lowest consistency but cheapest.

3) **Hybrid (prompt + reference image)**
   - Render current model to an image.
   - Use image-to-3D + text instructions.
   - More consistent than prompt-only, still provider dependent.

## UI Concepts
- Project view with revision timeline.
- "Refine" button adds a new revision prompt.
- Compare revisions and select a final version.

## Next Step When Implementing
- Choose provider that supports model refinement.
- Add `/jobs/{id}/revise` endpoint to create a new revision.
- Add `/projects` and `/projects/{id}` APIs for listing and history.
