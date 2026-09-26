from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


def solve_candidates(
    ranked: list[dict[str, Any]], *, limit: int, required_ids: set[str],
    policy: Mapping[str, Any], search_budget: int = 100_000,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if type(search_budget) is not int or search_budget < 1:
        raise ValueError("Craft search budget must be a positive integer")
    if len(ranked) > 256:
        raise KernelError("CRAFT_SEARCH_SCOPE_EXCEEDED", "Candidate pool exceeds the supported 256-card search scope; feasibility is unknown")
    identities = [item["knowledge_card_asset_version_id"] for item in ranked]
    if len(set(identities)) != len(identities):
        raise KernelError("CRAFT_SEARCH_INPUT_INVALID", "Candidate versions must be unique")
    mechanisms = [item["selected_content"].get("craft_mechanism") for item in ranked]
    names = [item["mechanism_id"] if item else "" for item in mechanisms]
    required = {index for index, identity in enumerate(identities) if identity in required_ids}
    if required_ids - set(identities):
        raise KernelError("MKAOS_REQUIRED_KNOWLEDGE_UNAVAILABLE", "Required cards absent from eligible pool: " + ", ".join(sorted(required_ids - set(identities))))
    dependencies = [set(item["composition"]["requires"]) if item else set() for item in mechanisms]
    conflicts = [set(item["composition"]["conflicting"]) if item else set() for item in mechanisms]
    precedes = [set(item["composition"]["precedes"]) if item else set() for item in mechanisms]
    dependency_only = {index for index, item in enumerate(ranked) if item.get("craft_assessment", {}).get("rejection_reason") == "CRAFT_NO_CONTEXT_MATCH" and index not in required}
    suffix_names: list[set[str]] = [set() for _ in range(len(ranked) + 1)]
    for index in range(len(ranked) - 1, -1, -1):
        suffix_names[index] = suffix_names[index + 1] | ({names[index]} if names[index] else set())
    visited = 0
    failures: set[str] = set()
    realization_cache = {}

    def realizable(chosen):
        nonlocal visited
        craft = tuple(i for i in chosen if names[i])
        if craft in realization_cache:
            return realization_cache[craft]
        if len(craft) > policy["max_uses_per_chapter"]:
            failures.add("chapter-use-capacity")
            return False
        full = (1 << len(craft)) - 1
        bundles = []
        for mask in range(1, full + 1):
            visited += 1
            if visited > search_budget:
                raise KernelError("CRAFT_SEARCH_BUDGET_EXHAUSTED", f"Search visited {search_budget} states; scene realization feasibility remains unknown")
            if mask.bit_count() > policy["max_uses_per_scene"]:
                continue
            group = [i for offset, i in enumerate(craft) if mask & (1 << offset)]
            group_names = {names[i] for i in group}
            if any(dependencies[i] - group_names or conflicts[i] & group_names for i in group):
                continue
            pending = {names[i]: precedes[i] & group_names for i in group}
            while pending:
                tails = {name for name, edges in pending.items() if not edges}
                if not tails:
                    break
                pending = {name: edges - tails for name, edges in pending.items() if name not in tails}
            if not pending:
                bundles.append(mask)
        allowances = []
        for i in craft:
            budget = ranked[i].get("craft_assessment", {}).get("budget_assessment", {})
            if policy["schema_version"] == "narrative-craft-budget.v3" and budget.get("temporal_budget_applied", True):
                allowances.append(0 if budget.get("in_cooldown") else max(0, policy["max_frequency_in_window"] - budget.get("frequency", 0)))
            else:
                allowances.append(policy["max_uses_per_chapter"])
        failed_allocations = set()

        def allocate(covered, counts):
            nonlocal visited
            if covered == full:
                return True
            key = (covered, counts)
            if key in failed_allocations:
                return False
            first_missing = (~covered & full) & -(~covered & full)
            for bundle in bundles:
                if not bundle & first_missing:
                    continue
                visited += 1
                if visited > search_budget:
                    raise KernelError("CRAFT_SEARCH_BUDGET_EXHAUSTED", "Scene allocation search budget exhausted; feasibility is unknown")
                following = tuple(count + bool(bundle & (1 << offset)) for offset, count in enumerate(counts))
                if sum(following) > policy["max_uses_per_chapter"] or any(count > allowance for count, allowance in zip(following, allowances, strict=True)):
                    continue
                if allocate(covered | bundle, following):
                    return True
            failed_allocations.add(key)
            return False

        result = allocate(0, (0,) * len(craft))
        realization_cache[craft] = result
        if not result:
            failures.add("scene-dependency-density-order-or-frequency")
        return result

    def search(index: int, chosen: tuple[int, ...], chosen_names: set[str], needed: set[str]) -> tuple[int, ...] | None:
        nonlocal visited
        visited += 1
        if visited > search_budget:
            raise KernelError("CRAFT_SEARCH_BUDGET_EXHAUSTED", f"Search visited {search_budget} states; no infeasibility conclusion is available")
        absent = needed - chosen_names - suffix_names[index]
        if absent:
            failures.update("missing-dependency:" + name for name in absent)
            return None
        if len(chosen) + len(required - set(chosen)) > limit:
            failures.add("total-card-capacity")
            return None
        if index == len(ranked):
            reachable = {names[i] for i in chosen if i not in dependency_only and names[i]}
            while True:
                expanded = reachable | {name for i in chosen if names[i] in reachable for name in dependencies[i]}
                if expanded == reachable:
                    break
                reachable = expanded
            if any(names[i] not in reachable for i in chosen if i in dependency_only):
                failures.add("orphan-dependency")
                return None
            return chosen if realizable(chosen) else None
        name = names[index]
        reason = ""
        if len(chosen) >= limit:
            reason = "total-card-capacity"
        elif name and len(chosen_names) >= policy["max_craft_candidates"]:
            reason = "craft-card-capacity"
        elif name and name in chosen_names:
            reason = "duplicate-mechanism:" + name
        elif name and (conflicts[index] & chosen_names or any(name in conflicts[i] for i in chosen)):
            reason = "conflict:" + identities[index]
        if not reason:
            found = search(index + 1, (*chosen, index), chosen_names | ({name} if name else set()), needed | dependencies[index])
            if found is not None:
                return found
        else:
            failures.add(reason)
        if index in required:
            return None
        return search(index + 1, chosen, chosen_names, needed)

    solution = search(0, (), set(), set())
    if solution is None:
        raise KernelError("MKAOS_REQUIRED_KNOWLEDGE_UNAVAILABLE", "Exhaustive eligible-pool search proved no combination for required cards " + ", ".join(sorted(required_ids)) + "; constraints=" + ", ".join(sorted(failures)))
    selected = [ranked[index] for index in solution]
    selected_names = {names[index] for index in solution if names[index]}
    rejected = []
    for index, item in enumerate(ranked):
        if index in solution:
            continue
        if names[index] and (conflicts[index] & selected_names or any(names[index] in conflicts[i] for i in solution)):
            reason = "CRAFT_COMPOSITION_CONFLICT"
        elif dependencies[index] - selected_names:
            reason = "CRAFT_DEPENDENCY_UNAVAILABLE"
        elif index in dependency_only:
            reason = "CRAFT_NO_CONTEXT_MATCH"
        elif names[index] in selected_names:
            reason = "CRAFT_MECHANISM_ALTERNATIVE"
        elif len(selected) >= limit:
            reason = "NARRATIVE_BANDWIDTH_LIMIT"
        else:
            reason = "CRAFT_CANDIDATE_BUDGET"
        rejected.append({"knowledge_card_asset_version_id": identities[index], "content_hash": item["content_hash"], "reason": reason, "applicability_assessment": item["applicability_assessment"]})
    return selected, rejected
