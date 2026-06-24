# Module Map

| Module | Package | Data Directory | Status |
|---|---|---|---|
| Ingestion | `modules/ingestion` | `data/raw` | executable through CLI |
| Cleaning | `modules/cleaning` | `data/cleaned` | executable through CLI |
| Decomposition | `modules/decomposition` | `data/decompositions` | mock executable |
| Knowledge | `modules/knowledge` | `data/knowledge` | mock executable |
| Materials | `modules/materials` | `data/materials` | mock executable |
| Topics | `modules/topics` | `data/topics` | mock executable |
| Worldbuilding | `modules/worldbuilding` | `data/worlds` | mock executable |
| Characters | `modules/characters` | `data/characters` | mock executable |
| Outline | `modules/outline` | `data/outlines` | mock executable |
| Chapter Plan | `modules/chapter_plan` | `data/chapter_plans` | mock executable |
| Drafting | `modules/drafting` | `data/drafts` | mock executable |
| Review | `modules/review` | `data/reviews` | mock executable |
| Revision | `modules/revision` | `data/reviews` | mock executable |
| Feedback | `modules/feedback` | `data/feedback` | mock executable |
| Training | `modules/training` | `data/training` | schema ready |
| Image Prompts | `modules/image_prompts` | `data/image_prompts` | schema ready |
| Skills | `skills/` | docs-backed capability layer | 14 validated Skills |

## Service Boundary

P0 workflow step logic lives in `src/novel_forge/modules/<module>/service.py`.
`src/novel_forge/workflows/pipeline.py` is kept as the orchestration and compatibility layer: it initializes storage, preserves the public workflow function names used by the CLI/tests, runs the sample pipeline, and performs project validation.
