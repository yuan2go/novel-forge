# Test Novel Problem List

## P0 Blockers

| Problem | Text Evidence | System Defect | Required Fix |
|---|---|---|---|
| Protagonist drift | `顾砚秋`, `江砚`, `沈砚`, `阿照` all occupy lead/investigator slots | No Canon Database or forbidden alias gate | `canon_database`, canon gate, revision task |
| Organization drift | `夜档司`, `巡遗司`, `北档房`, `遗簿库`, `夜档库` blur together | No organization canon | organization entities and alias policy |
| Metadata leakage | Chapter 072 and 097 contain JSON wrappers | No Output Sanitizer before storage/publish | sanitizer hard fail |
| Repeated chapter skeleton | abnormal object -> test -> bureau pressure -> counter-rule -> old debt | No Pattern Similarity Checker | fingerprint and recent-window gate |
| Missing chapter state | liabilities, clues, debts not stored as next-chapter state | Context relies on prose memory | `chapter_state` extraction and injection |
| No unified hard gate | Bad chapters can become release packages as blocked evidence only after late audit | Publish gate lacked long-form stability checks | longform gate inside publish gate |

## P1 High Risks

| Problem | Impact | Required Fix |
|---|---|---|
| Arc expansion without closure | Reader loses the main question | `arc_plan`, 10-chapter payoff check |
| Infinite clues | Clues feel interchangeable | `foreshadowing_graph`, target truth required |
| Motif overload | Style turns into repeated token set | `motif_budget_report` |
| Debt abuse | Mentor debt becomes universal hook | `character_state_ledger` with Debt Ledger |
| Antagonist absence | No durable opponent | `villain_operation_plan` |

## P2 Product Risks

| Problem | Impact | Required Fix |
|---|---|---|
| Reader fatigue | Late chapters feel mechanically similar | `reader_fatigue_report` |
| Static style | Investigation, confrontation, and payoff scenes sound alike | `style_control_plan` |
| Platform ambiguity | Commercial package unclear | `platform_adapter_report` |
| Low reward visibility | Protagonist pays costs without enough gains | `reward_ledger` |
| Review not executable | Natural-language reviews do not become tasks | structured review score and revision task generation |
