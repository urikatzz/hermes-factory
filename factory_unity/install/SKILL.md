---
name: unity-scene
description: Assemble a real Unity scene from a layout, render it with the Unity engine, and hand the capture to the full-scene similarity gate. Project-agnostic.
---

# Unity scene assembly and capture

Use this at final integration of a game with a human-approved visual reference. The result is judged on a **real engine render of the whole scene**, never on isolated sprites and never on an image anybody painted or generated.

`CAPTURE` = `python3 ${HERMES_SKILL_DIR}/scripts/unity_scene_capture.py`

## 1. The layout (`art/scene/scene-layout.json`, schema `factory-scene-layout/v1`)

```json
{"schema": "factory-scene-layout/v1", "scene": "Assets/Scenes/FactoryScene.unity", "lighting": "unlit",
 "camera": {"orthographic": true, "size": 6.1875, "position": [0, 0, -10], "background": [0.04, 0.04, 0.05, 1], "width": 1920, "height": 1080},
 "objects": [{"id": "wall", "name": "Wall", "asset": "Assets/Art/Room01/wall.png", "position": [0, 0, 0], "size_units": [29.4], "sorting_order": 0, "covers": ["V1"]}]}
```

- One object per delivered asset. `asset` is an `Assets/` path inside the project; `position` is world units; `size_units` is the sprite's WIDTH in world units (height follows the image's aspect); `sorting_order` decides what draws on top.
- `covers` lists the approved-reference requirement ids the object supplies (`V3`, ...). An approved requirement that no object covers is **missing**: the scene can still be rendered and scored, but only as a preliminary composition test, never accepted.
- The camera matches the reference: same aspect ratio and resolution, and the orthographic size from the plan's scale. `lighting` is `unlit` (assets as authored, default) or `project` (the project's own 2D lighting).
- Place objects from the plan's coordinates, not by eye. Build the layout from every asset and requirement the plan names; do not leave something out because it is hard.

## 2. Capture

`CAPTURE --project PROJECT_DIR --layout art/scene/scene-layout.json --out <workspace>/scene --required V1,V2,...` (the approved requirement ids from the card; `--deferred` only for ids a human deferred).

It clones the project into scratch (the project itself is never modified, and it works while a person has the project open in the Editor), installs the factory editor script in the clone, runs Unity in batch mode, and then verifies every claim the engine makes against the files (engine version, graphics device, screenshot hash, scene hash, the layout that was built, every asset's hash). Only a verified capture is written. Output: `scene.png`, `scene-render.json` (factory-scene-render/v1 with the engine's own attestation and the completeness of the scene), `engine-capture.json`, the built scene and `unity.log`.

Exit 0: captured and verified. Exit 3: not captured (`stage` says why: layout, engine, verify). Never substitute another image; report the stage and message.

## 3. Score and repair

The reviewer scores `scene.png` against the ORIGINAL approved reference with the art-review skill's `scene_score.py` (pass is 80/100, and the scene must be complete and engine-attested). Below 80 the ranked differences name the responsible asset or `scene settings` (placement, camera, sorting, lighting in the layout); repair those and capture again. A repair changes only what was blamed.
