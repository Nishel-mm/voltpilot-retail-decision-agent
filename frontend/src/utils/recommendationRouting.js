/** Resolve a seven-risk-area finding to a matching pending agent decision.
 * This is intentionally conservative: don't send a user to a decision for a
 * different product or store just because it happens to be top-ranked.
 */
export function normalizeLabel(value) {
  return String(value ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function hasOptionType(item, type) {
  return Array.isArray(item?.options) && item.options.some((option) => option?.type === type);
}

function relevanceForArea(areaId, item) {
  const issueType = String(item?.issue_type || "").toLowerCase();
  switch (areaId) {
    case "stockout":
      if (issueType === "stockout_risk") return 50;
      if (issueType === "promo_stockout") return 45;
      if (issueType === "delayed_po") return 30;
      return 0;
    case "ageing":
      return issueType === "ageing_stock" ? 70 : 0;
    case "promotions":
      if (issueType === "promo_stockout") return 70;
      if (issueType === "stockout_risk") return 30;
      return 0;
    case "launches":
      return 0; // the current detector correctly reports missing launch data
    case "suppliers":
      return hasOptionType(item, "purchase") ? 50 : 0;
    case "imbalance":
      return hasOptionType(item, "transfer") ? 55 : 0;
    case "purchase-orders":
      if (issueType === "delayed_po") return 100;
      // A PO may be surfaced in a stockout or promotion recommendation when
      // its delivery delay is part of the same risk. The exact PO check below
      // prevents linking to an unrelated decision for the same product/store.
      return hasOptionType(item, "expedite_po") ? 75 : 0;
    default:
      return 0;
  }
}

export function findMatchingDecision(areaId, finding, recommendations) {
  if (!finding || areaId === "launches") return null;
  const product = normalizeLabel(finding.product);
  const store = normalizeLabel(finding.store);
  if (!product || product === "—" || product === "") return null;

  const pendingItems = (recommendations || []).filter((item) => String(item.status).toLowerCase() === "pending");
  const candidates = [];
  for (const item of pendingItems) {
    if (normalizeLabel(item.product_name) !== product) continue;
    const relevance = relevanceForArea(areaId, item);
    if (!relevance) continue;

    if (areaId === "purchase-orders") {
      const poNumber = normalizeLabel(finding.metrics?.po_number);
      if (poNumber) {
        const searchable = normalizeLabel([
          item.title,
          item.why_now,
          ...(Array.isArray(item.evidence) ? item.evidence : []),
          ...(Array.isArray(item.options) ? item.options.map((option) => option?.title || "") : []),
          ...(Array.isArray(item.options) ? item.options.flatMap((option) => option?.evidence || []) : []),
        ].join(" "));
        if (!searchable.includes(poNumber)) continue;
      } else if (String(item.issue_type || "").toLowerCase() !== "delayed_po") {
        continue;
      }
    }

    // Supplier comparisons apply to a product across the network. Every other
    // detector is store-specific, so require the same store before routing.
    if (areaId !== "suppliers" && store && store !== "multi store supply" && store !== "—") {
      if (normalizeLabel(item.store_name) !== store) continue;
    }

    let score = relevance;
    if (store && store !== "multi store supply" && normalizeLabel(item.store_name) === store) score += 20;
    if (item.status === "pending") score += 10;
    candidates.push({ item, score });
  }

  candidates.sort((a, b) => b.score - a.score || Number(b.item.score || 0) - Number(a.item.score || 0));
  return candidates[0]?.item || null;
}
