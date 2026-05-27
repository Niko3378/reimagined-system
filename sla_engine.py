from datetime import datetime, timedelta

# Délais SLA en heures par priorité
SLA_DELAYS = {
    "critique": 4,
    "haute":    8,
    "normale":  24,
    "faible":   72,
}


def get_sla_status(ticket) -> dict:
    """Retourne le statut SLA d'un ticket."""
    if ticket.status in ("resolu", "ferme"):
        return {"status": "resolved", "remaining_h": None, "pct": 100, "label": "Résolu"}

    limit_h = SLA_DELAYS.get(ticket.priority, 24)
    reference = ticket.created_at
    if reference is None:
        return {"status": "unknown", "remaining_h": None, "pct": 0, "label": "Inconnu"}

    elapsed = datetime.utcnow() - reference
    elapsed_h = elapsed.total_seconds() / 3600
    remaining_h = limit_h - elapsed_h
    pct_used = min(100, (elapsed_h / limit_h) * 100)
    pct_remaining = max(0, 100 - pct_used)

    if remaining_h < 0:
        status = "breach"
        label = f"Dépassé de {abs(remaining_h):.1f}h"
    elif pct_remaining < 25:
        status = "warning"
        label = f"{remaining_h:.1f}h restantes"
    else:
        status = "ok"
        label = f"{remaining_h:.1f}h restantes"

    return {
        "status": status,
        "remaining_h": round(remaining_h, 1),
        "elapsed_h": round(elapsed_h, 1),
        "limit_h": limit_h,
        "pct_remaining": round(pct_remaining, 1),
        "label": label,
    }


def get_sla_summary(tickets) -> dict:
    counts = {"ok": 0, "warning": 0, "breach": 0, "resolved": 0}
    for t in tickets:
        s = get_sla_status(t)["status"]
        if s in counts:
            counts[s] += 1
    return counts
