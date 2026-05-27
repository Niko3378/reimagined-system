from datetime import datetime, timedelta

# Priorité suggérée selon le type de ticket
TYPE_PRIORITY = {
    "intrusion":             "critique",
    "alerte_securite":       "critique",
    "perte_donnees":         "critique",
    "virus":                 "critique",
    "corruption_donnees":    "critique",
    "panne":                 "haute",
    "coupure_reseau":        "haute",
    "surcharge_systeme":     "haute",
    "panne_electrique":      "haute",
    "phishing":              "haute",
    "indisponibilite_service": "haute",
    "incident":              "normale",
    "dysfonctionnement":     "normale",
    "crash_application":     "normale",
    "acces_refuse":          "normale",
    "ecran_bleu":            "normale",
    "peripherique_defaillant": "normale",
    "erreur_reseau":         "haute",
    "ransomware":            "critique",
    "fuite_donnees":         "critique",
    "defaillance_serveur":   "critique",
    "vol_equipement":        "haute",
    "coupure_telephonie":    "haute",
    "spam_massif":           "normale",
    "probleme_impression":   "faible",
    "demande":               "faible",
    "demande_acces":         "faible",
    "demande_installation":  "faible",
    "demande_materiel":      "faible",
    "demande_information":   "faible",
    "demande_formation":     "faible",
    "demande_sauvegarde":    "faible",
    "demande_demenagement":  "faible",
    "demande_licence":       "faible",
    "demande_reinitialisation_mdp": "faible",
    "demande_creation_compte":      "faible",
    "demande_assistance":    "faible",
    "demande_configuration": "faible",
    "demande_mise_a_jour":   "faible",
    "demande_archivage":     "faible",
    "demande_deblockage_compte": "faible",
    "demande_vpn":           "faible",
    "demande_messagerie":    "faible",
    "demande_impression_config": "faible",
    "demande_badge_acces":   "faible",
    "demande_onboarding":    "normale",
    "demande_offboarding":   "normale",
    "demande_audit_securite": "faible",
    "demande_intervention_site": "normale",
    "demande_certificat_ssl": "normale",
}

PRIORITY_ORDER = ["faible", "normale", "haute", "critique"]

# Délai avant escalade (en heures)
ESCALATION_DELAYS = {
    "faible":  168,  # 7 jours
    "normale":  72,  # 3 jours
    "haute":    24,  # 24 heures
}


def suggest_priority(ticket_type: str) -> str:
    return TYPE_PRIORITY.get(ticket_type, "normale")


def next_priority(current: str) -> str | None:
    idx = PRIORITY_ORDER.index(current)
    if idx < len(PRIORITY_ORDER) - 1:
        return PRIORITY_ORDER[idx + 1]
    return None


def should_escalate(ticket) -> bool:
    if ticket.status in ("resolu", "ferme"):
        return False
    if ticket.priority == "critique":
        return False
    delay_hours = ESCALATION_DELAYS.get(ticket.priority)
    if delay_hours is None:
        return False
    reference = ticket.updated_at or ticket.created_at
    if reference is None:
        return False
    return datetime.utcnow() - reference > timedelta(hours=delay_hours)
