# EP01 single-hero character gate — 吉皮提 / CHAR_GPT

## Actual goal

Produce **one** original, cinema-usable, consistently modeled, rigged character
in **Windows Unreal Engine 5.8**, matching the existing Director Studio
`WaitingOffice / EP01 / CHAR_GPT` character card. A successful Blueprint
creation or successful six-frame render is **not** an acceptable substitute.

The earlier V1.0 block-and-sphere review Blueprints are *reference placeholders*.
Never approve, publish, or relabel them as final masters.

## Hard identity lock (from Director Studio, revision 2)

- Name: 吉皮提; calm, kind, thoughtful, reliable, original young female anime character.
- Hair: **short, neck-length dark chestnut**, naturally side-parted. Never silver,
  white, long, or twin-tails.
- Eyes: **amber-brown**, not teal/green.
- Outfit: **ivory long coat**, muted teal inner panels/details, dark gray trousers,
  comfortable short ankle boots. Small crossed seams and quiet layered fabric
  details, no oversized breast pin or mark.
- No official OpenAI/ChatGPT logo, simulated six-ring mark, or printed trademarks.
- The same character, proportions, clothing, and accessories MUST remain stable
  in front / left profile / back views and all animation takes.
- Expression targets: natural smile, serious, thinking, surprised, comforting,
  confused, wry smile, determined. Do not accept interchangeable generic faces.

## Production route (UE 5.8)

1. Verify MetaHuman Character plugin, Creator Core Data, project configuration,
   Epic account cloud authentication, and a supported UE Cine assembly path.
   The new Worker preflight reports filesystem facts only; it deliberately
   does **not** assert Core Data, authentication or rig readiness.
2. Start from an appropriate authored stylized **human mesh** matching the
   locked 2D concept (or a close MetaHuman preset sculpted and verified
   against all three orthographic views), NOT from the V1.0 sphere Actor.
   MetaHuman `From Custom Mesh` supports 5.8 source body/head fitting.
3. Create exactly one candidate **in a job-owned EP01 folder**. Do not alter
   the existing V1.0 cast build or any approved/master asset.
4. Sculpt head/body; use cinema-grade skin, realistic spatial eye placement,
   strand/hair-card grooming appropriate for the stylized reference, and an
   original wardrobe. Preserve the locked colors and silhouette.
5. Run full face rig with blendshapes, body skeleton, compatible groom and
   clothing, and high-resolution textures through verified Epic services.
   Account access, installed Core Data and signed-in editor are prerequisites.
6. Assemble through **UE Cine** and verify genuine `SkeletalMesh`, skeleton,
   face deformations, correct blueprint binding and full wardrobe. An
   assembled generic preset alone fails the creative check.
7. Produce **real UE MRQ** evidence: 3 orthographic full-body views, a
   360-degree rotation, close-ups (face/eyes/hair/cuffs/coat/boots) and
   eight labeled expression renders. Preserve source PNG SHA-256 receipts.
8. Animate a minimum three-second conversational take with facial movement
   and a body gesture. Check geometry/rig, no clipping, no drifting eye lines,
   no popping groom, and no hand/clothes intersections.
9. Director reviews candidate against the original stored character card.
   **Never auto-promote to an approved Studio character master.**

## Binary acceptance gates

| Gate | Must be proven | Rejection |
| --- | --- | --- |
| Identity | Hair, amber eyes, silhouette, wardrobe match CHAR_GPT revision 2 | Color drift / wrong hairstyle |
| Structure | Native skeletal body + functional facial rig | Static meshes, cylinders or sphere-faces |
| Performance | Eight distinct expressions + talking/gesture take | Static head or no deformation |
| Continuity | Same body/outfit/face across multi-view renders | Identity drift, inconsistent seams |
| Render | Genuine UE 5.8 MRQ screenshots and source receipts | Mockups, composite or unverifiable ZIP |
| Ownership | Candidate assets isolated; master stays unapproved until reviewed | Overwriting old projects or auto-approval |

The word **"perfect" is the director's quality judgment, not an automated
status code**. Report actual deficiencies rather than claim 100% completion.

## Current verified production blockers (2026-11-12)

- UE Worker 1.2.1 runs Unreal Engine 5.8 on Windows RTX 4090.
- V1.2 cast review fixed severe overexposure, **not** actual body modeling.
- Fixed Director `.uproject` manifest does not include the MetaHuman
  Character/Creator plugin. Worker currently accepts the previous strict
  minimal manifest; enabling MetaHuman will require a reviewed project
  migration to avoid breaking existing jobs.
- Director Studio has the reference character card; **no approved 3D master**.
- EP01 native approved asset audit returned `CHAR_GPT exists=false`.
- Worker's existing RPC allowlist has no MetaHuman character generation,
  MetaHuman rigging, wardrobe import, or face animation job yet.

**This project must not repeat five-placeholders rendering as progress
towards the one finished hero.**
