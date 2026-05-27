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
    "lenteur_systeme":              "haute",
    "mise_a_jour_echouee":          "normale",
    "certificat_expire":            "haute",
    "sauvegarde_echouee":           "haute",
    "attaque_ddos":                 "critique",
    "acces_non_autorise":           "critique",
    "perte_connexion_wifi":         "normale",
    "messagerie_indisponible":      "haute",
    "partage_reseau_inaccessible":  "normale",
    "application_lente":            "normale",
    "ecran_noir":                   "normale",
    "clavier_souris_defaillant":    "faible",
    "son_defaillant":               "faible",
    "logiciel_non_autorise":        "haute",
    "erreur_connexion_vpn":         "normale",
    "synchronisation_echouee":      "normale",
    "onduleur_defaillant":          "haute",
    "stockage_plein":               "haute",
    "usurpation_identite":          "critique",
    "base_donnees_corrompue":       "critique",
    "incompatibilite_logicielle":   "normale",
    "camera_defaillante":           "faible",
    "perte_connexion_internet":     "haute",
    "interruption_cloud":           "haute",
    "erreur_authentification":      "normale",
    "demande_extension_stockage":      "faible",
    "demande_redirection_mail":        "faible",
    "demande_groupe_securite":         "faible",
    "demande_partage_reseau":          "faible",
    "demande_restauration":            "normale",
    "demande_tele_travail":            "faible",
    "demande_poste_remplacement":      "normale",
    "demande_mise_en_service":         "normale",
    "demande_chiffrement":             "normale",
    "demande_double_authentification": "faible",
    "demande_revision_droits":         "normale",
    "demande_telephone_ip":            "faible",
    "demande_nettoyage_poste":         "faible",
    "demande_migration_donnees":       "normale",
    "demande_formation_securite":      "faible",
    "demande_mise_a_jour_firmware":    "faible",
    "demande_salle_reunion":           "faible",
    "demande_signature_mail":          "faible",
    "demande_rapport_activite":        "faible",
    "demande_antivirus":               "faible",
    "demande_scan_securite":           "normale",
    "demande_connexion_bureau_distant": "faible",
    "demande_acces_applicatif":        "faible",
    "demande_supervision":             "faible",
    "demande_changement_mdp":          "faible",
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
