# CAD Integrations

Pulsai stays web-first. CAD integrations are bridges, not replacements for the
build123d engine.

## Recommendation

1. **Onshape first** for direct CAD integration.
   - Fits the online product: browser-based, cloud documents, OAuth/API access.
   - Best first workflow: connect Onshape, pick a document/Part Studio, import
     as STEP, edit/augment in Pulsai, export STEP back for review.
   - Later workflow: push a new Onshape version or add generated geometry back
     through the API.

2. **Fusion as handoff first, optional local bridge later.**
   - Best first workflow: export STEP and setup notes for Fusion.
   - Optional pro workflow: local Fusion MCP bridge when the user has Fusion
     installed and running.
   - Cloud workflow: Autodesk Fusion Automation API is useful for server-side
     batch automation later, but it is heavier and should not block the maker
     loop.

## Why Onshape First

Onshape is cloud-native, so it matches a hosted web app. A user can authorize
Pulsai, select a document, and let the backend export a Part Studio as STEP.
No local desktop CAD install is required.

Phase 1 scope:

- Add `ONSHAPE_CLIENT_ID`, `ONSHAPE_CLIENT_SECRET`, and callback URL config.
- Add OAuth connect/disconnect flow.
- List recent documents and Part Studios.
- Import selected Part Studio as STEP via the existing `/design/import-cad`
  pipeline.
- Store only document/workspace/version/element IDs plus import metadata.

Out of scope for Phase 1:

- Editing native Onshape feature history.
- Writing FeatureScript.
- Bidirectional live sync.
- Team permissions beyond the user's Onshape authorization.

## Fusion Options

### Export/Handoff

This is the default. Pulsai exports STEP, STL, DXF, and setup notes. The user
opens the STEP in Fusion manually. It works for every user without requiring a
local bridge.

### Local Fusion MCP

Autodesk documents a Fusion MCP server for AI tools. This is powerful but local:
the user needs Fusion installed and running, and Pulsai would need a local
helper/bridge to talk to that MCP server from the browser product.

Use this only as an optional pro mode:

- "Open current STEP in Fusion"
- "Ask Fusion to measure/check selected body"
- "Round-trip a modified STEP back into Pulsai"

### Fusion Automation API

Autodesk Platform Services has Fusion Automation for cloud jobs. It is the
right candidate later for automated conversion, CAM preparation, or batch
validation. It should not be the primary interactive editor because it adds
account, cost, queueing, and job-state complexity.

## Product Rule

Never require Fusion, Onshape, or any other CAD account for the core maker flow.
The product must still work as:

`describe -> see -> edit -> validate -> export/print`

CAD integrations are accelerators for pro users and designer handoff.

## References

- Onshape API: https://www.onshape.com/en/blog/cloud-native-cad-rest-api
- Fusion MCP: https://help.autodesk.com/view/ADSKMCP/ENU/
- Fusion Automation API: https://aps.autodesk.com/blog/design-automation-api-fusion-now-generally-available
