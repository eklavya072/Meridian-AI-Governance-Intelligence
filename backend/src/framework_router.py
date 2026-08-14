from __future__ import annotations

import structlog
from functools import lru_cache
from typing import Any

from src.framework_sync import load_frameworks_config

logger = structlog.get_logger()

# ─────────────────────────────────────────────────────────────────────────
# Deterministic framework routing for Module 1 (Governance Dimension
# Evaluation). The LLM never decides which frameworks are searched — this
# module does, entirely in backend code, before any vector retrieval.
#
# Rules:
#   1. CORE_FRAMEWORKS are always searched, for every governance dimension.
#   2. Frameworks tagged `dimensions: [X]` in config/frameworks.yaml are
#      searched only when evaluating dimension X.
#   3. Frameworks tagged `regions: [ASEAN | AU | ...]` are searched only
#      when the uploaded document's country belongs to that region.
#   4. Routing is deterministic: same input → same ordered framework list.
# ─────────────────────────────────────────────────────────────────────────

CORE_FRAMEWORKS: list[str] = [
    "UNESCO Recommendation on the Ethics of AI",
    "OECD AI Principles",
    "UNDP Digital Strategy 2022-2025",
    "UN Global Digital Compact",
    "UN Roadmap for Digital Cooperation",
    "EU AI Act (Regulation (EU) 2024/1689)",
    "NIST AI Risk Management Framework 1.0",
]

# Region → normalized country names (lowercase, exact-match after normalize).
# Aliases are listed explicitly so "Viet Nam" / "Vietnam", "Côte d'Ivoire" /
# "Cote d'Ivoire", etc. resolve without fuzzy matching.
REGION_COUNTRIES: dict[str, set[str]] = {
    "ASEAN": {
        "brunei", "brunei darussalam", "cambodia", "indonesia", "laos",
        "lao pdr", "lao people's democratic republic", "malaysia", "myanmar",
        "philippines", "singapore", "thailand", "vietnam", "viet nam",
        "timor-leste", "timor leste",
    },
    "AU": {
        "algeria", "angola", "benin", "botswana", "burkina faso", "burundi",
        "cabo verde", "cape verde", "cameroon", "central african republic",
        "chad", "comoros", "congo", "republic of the congo", "democratic republic of the congo",
        "drc", "côte d'ivoire", "cote d'ivoire", "ivory coast", "djibouti",
        "egypt", "equatorial guinea", "eritrea", "eswatini", "swaziland",
        "ethiopia", "gabon", "gambia", "ghana", "guinea", "guinea-bissau",
        "kenya", "lesotho", "liberia", "libya", "madagascar", "malawi", "mali",
        "mauritania", "mauritius", "morocco", "mozambique", "namibia", "niger",
        "nigeria", "rwanda", "são tomé and príncipe", "sao tome and principe",
        "senegal", "seychelles", "sierra leone", "somalia", "south africa",
        "south sudan", "sudan", "tanzania", "togo", "tunisia", "uganda",
        "zambia", "zimbabwe",
    },
}


def _normalize_country(country: str | None) -> str:
    return (country or "").strip().lower().replace("_", " ")


def resolve_regions(country: str | None) -> list[str]:
    """Return the region names (ASEAN, AU, ...) a country belongs to."""
    if not country:
        return []
    c = _normalize_country(country)
    if not c:
        return []
    regions: list[str] = []
    for region, names in REGION_COUNTRIES.items():
        if c in names:
            regions.append(region)
    if not regions:
        logger.debug("country_region_unresolved", country=country)
    return regions


@lru_cache(maxsize=1)
def _routing_metadata() -> tuple[dict[str, tuple[tuple[str, tuple[str, ...]], ...]], dict[str, tuple[str, ...]]]:
    """Build dimension → (framework name, roles) and region → framework names
    from config/frameworks.yaml routing tags. Roles are kept so dimension-
    tagged Module 2/3 sources can be resolved separately from Module 1
    normative routing (they must NOT leak into Module 1's framework list).
    Cached: the config is static at runtime, and routing must be
    deterministic per process."""
    dim_map: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    region_map: dict[str, list[str]] = {}
    for fw in load_frameworks_config():
        name = fw.get("name", "")
        if not name:
            continue
        roles = tuple(fw.get("roles") or [])
        for d in (fw.get("dimensions") or []):
            dim_map.setdefault(d, []).append((name, roles))
        for r in (fw.get("regions") or []):
            if r and r != "Global":
                region_map.setdefault(r, []).append(name)
    return (
        {k: tuple(v) for k, v in dim_map.items()},
        {k: tuple(v) for k, v in region_map.items()},
    )


def resolve_dimension_frameworks(
    dimension: str, roles: list[str] | None = None
) -> list[str]:
    """Dimension-tagged frameworks, optionally restricted to specific roles.

    Module 1 routing filters to module_1_normative (see resolve_frameworks).
    Module 2 and Module 3 call this with ["module_2_practical"] /
    ["module_3_implementation"] so a dimension-tagged practical tool or
    implementation source is guaranteed Module 2/3 budget for its dimension
    (same regional-reserve idea, extended to dimension tags).
    """
    dim_map, _ = _routing_metadata()
    role_set = set(roles or [])
    names: list[str] = []
    for name, fw_roles in dim_map.get(dimension, ()):
        if not role_set or (role_set & set(fw_roles)):
            names.append(name)
    return names

def resolve_regional_frameworks(country: str | None = None) -> list[str]:
    """The region-routed frameworks for a country (subset of resolve_frameworks).

    Returns exactly the frameworks selected purely because the document's
    country belongs to a routed region (e.g. the Singapore Model AI
    Governance Framework for ASEAN countries, the AU Continental Strategy
    for AU members). Retrieval uses this to reserve Module 1 budget for the
    country's own frameworks so they cannot lose every slot to the always-on
    core frameworks on similarity alone.
    """
    _, region_map = _routing_metadata()
    regions = resolve_regions(country)
    names: list[str] = []
    for region in regions:
        names.extend(region_map.get(region, ()))
    # Deduplicate preserving order (region sets can overlap in theory).
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def resolve_frameworks(dimension: str, country: str | None = None) -> list[str]:
    """Deterministic framework list for one dimension's Module 1 retrieval.

    Core frameworks always; dimension-specific frameworks only for the
    matching dimension; regional frameworks only for the matching region.
    Order is stable: core, then dimension-specific (sorted by config order),
    then regional. Unindexed frameworks in the result are harmless — vector
    retrieval simply returns nothing for them.
    """
    dim_map, region_map = _routing_metadata()

    regions = resolve_regions(country)
    selected: list[str] = list(CORE_FRAMEWORKS)
    # Only module_1_normative dimension-tagged frameworks participate in
    # Module 1 routing — a Module 2/3 source tagged for the same dimension
    # must never be added to Module 1's framework list (it has no normative
    # chunks, and its role is served by the Module 2/3 reserve instead).
    selected.extend(
        name
        for name, fw_roles in dim_map.get(dimension, ())
        if "module_1_normative" in fw_roles
    )
    for region in regions:
        selected.extend(region_map.get(region, ()))

    # Deduplicate preserving order (a framework can be both core and tagged).
    seen: set[str] = set()
    ordered: list[str] = []
    for name in selected:
        if name not in seen:
            seen.add(name)
            ordered.append(name)

    logger.info(
        "framework_route_resolved",
        dimension=dimension,
        country=country,
        regions=regions,
        num_frameworks=len(ordered),
        frameworks=ordered,
    )
    return ordered
