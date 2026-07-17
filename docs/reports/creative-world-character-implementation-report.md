# Creative, World, and Character Implementation Report

| Capability | Domain core | Authority definition | Gate | Tests | Commit |
|---|---|---|---|---|---|
| CreativeBrief | required reader/genre/mechanism/theme/serialization/source/quality goals | `creative.brief.create` | concrete ThemeQuestion | `test_creative_domain` | `8179163`, `5aa2a89` |
| Candidate pool | mechanism fingerprint evaluation | `creative.candidates.evaluate` | long-form, readability, novelty, originality | same | same |
| Clustering/proposal | fingerprint clustering + ranked proposal | `creative.candidates.cluster`, `creative.project.approve` | operator approval required | same | same |
| WorldBible | rules plus factions/institutions/resources/systems/economy/hierarchy/history/daily-life | `production.world.generate` | cost, consequence, conflict and unlimited-capability checks | `test_worldbuilding_domain` | `52a3e39`, `5aa2a89` |
| Character/relationship | desire/need/fear/wound/belief/agency/voice/arcs/capability cost and evolving relationship state | `production.character.generate`, `character.relationships.generate` | project isolation, required agency/cost/state | `test_character_domain` | `acd0511`, `5aa2a89` |

These operations are `handler_bound` and disabled pending PostgreSQL integration proof. They are implemented deterministic evaluators/builders over provider- or operator-supplied candidates, not a second model protocol and not real-provider proof.
