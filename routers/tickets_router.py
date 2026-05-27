from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, timedelta
import csv
import io
import models
import schemas
import auth
from database import get_db
from notifications import broadcaster
from priority_engine import suggest_priority
from sla_engine import get_sla_status, get_sla_summary, SLA_DELAYS

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

VALID_STATUSES = {"ouvert", "en_cours", "resolu", "ferme"}
VALID_PRIORITIES = {"faible", "normale", "haute", "critique"}
INCIDENT_TYPES = {
    "incident","panne","dysfonctionnement","alerte_securite","coupure_reseau","intrusion",
    "perte_donnees","surcharge_systeme","panne_electrique","virus","phishing","crash_application",
    "corruption_donnees","indisponibilite_service","acces_refuse","ransomware","erreur_reseau",
    "ecran_bleu","peripherique_defaillant","probleme_impression","vol_equipement","fuite_donnees",
    "spam_massif","defaillance_serveur","coupure_telephonie",
    "lenteur_systeme","mise_a_jour_echouee","certificat_expire","sauvegarde_echouee",
    "attaque_ddos","acces_non_autorise","perte_connexion_wifi","messagerie_indisponible",
    "partage_reseau_inaccessible","application_lente","ecran_noir","clavier_souris_defaillant",
    "son_defaillant","logiciel_non_autorise","erreur_connexion_vpn","synchronisation_echouee",
    "onduleur_defaillant","stockage_plein","usurpation_identite","base_donnees_corrompue",
    "incompatibilite_logicielle","camera_defaillante","perte_connexion_internet",
    "interruption_cloud","erreur_authentification",
}
DEMANDE_TYPES  = {
    "demande","demande_acces","demande_installation","demande_materiel","demande_information",
    "demande_formation","demande_sauvegarde","demande_demenagement","demande_licence",
    "demande_reinitialisation_mdp","demande_creation_compte","demande_assistance",
    "demande_configuration","demande_mise_a_jour","demande_archivage","demande_deblockage_compte",
    "demande_vpn","demande_messagerie","demande_impression_config","demande_badge_acces",
    "demande_onboarding","demande_offboarding","demande_audit_securite","demande_intervention_site",
    "demande_certificat_ssl",
    "demande_extension_stockage","demande_redirection_mail","demande_groupe_securite",
    "demande_partage_reseau","demande_restauration","demande_tele_travail",
    "demande_poste_remplacement","demande_mise_en_service","demande_chiffrement",
    "demande_double_authentification","demande_revision_droits","demande_telephone_ip",
    "demande_nettoyage_poste","demande_migration_donnees","demande_formation_securite",
    "demande_mise_a_jour_firmware","demande_salle_reunion","demande_signature_mail",
    "demande_rapport_activite","demande_antivirus","demande_scan_securite",
    "demande_connexion_bureau_distant","demande_acces_applicatif","demande_supervision",
    "demande_changement_mdp",
}
VALID_TYPES = INCIDENT_TYPES | DEMANDE_TYPES
VALID_CATEGORIES = {"materiel", "logiciel", "reseau", "securite", "telephonie", "imprimante", "autre"}


def _record_history(db, ticket_id: int, user_id: int, field: str, old_val, new_val):
    entry = models.TicketHistory(
        ticket_id=ticket_id,
        user_id=user_id,
        field_changed=field,
        old_value=str(old_val) if old_val is not None else None,
        new_value=str(new_val) if new_val is not None else None,
    )
    db.add(entry)


@router.get("/", response_model=List[schemas.TicketListOut])
def list_tickets(
    status: Optional[str] = Query(None),
    statuses: Optional[str] = Query(None),       # ex: "ouvert,en_cours"
    type: Optional[str] = Query(None),
    type_group: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    priorities: Optional[str] = Query(None),     # ex: "haute,critique"
    category: Optional[str] = Query(None),
    assigned_to_id: Optional[int] = Query(None),
    creator_id: Optional[int] = Query(None),
    unassigned: bool = Query(False),
    mine: bool = Query(False),
    search: Optional[str] = Query(None),
    full_text: Optional[str] = Query(None),       # recherche titre + description
    date_from: Optional[str] = Query(None),       # YYYY-MM-DD
    date_to: Optional[str] = Query(None),         # YYYY-MM-DD
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    q = db.query(models.Ticket)
    if mine:
        q = q.filter(models.Ticket.created_by_id == current_user.id)
    if creator_id is not None:
        q = q.filter(models.Ticket.created_by_id == creator_id)
    if statuses:
        q = q.filter(models.Ticket.status.in_(statuses.split(",")))
    elif status:
        q = q.filter(models.Ticket.status == status)
    if type:
        q = q.filter(models.Ticket.type == type)
    if type_group == "incident":
        q = q.filter(models.Ticket.type.in_(INCIDENT_TYPES))
    elif type_group == "demande":
        q = q.filter(models.Ticket.type.in_(DEMANDE_TYPES))
    if priorities:
        q = q.filter(models.Ticket.priority.in_(priorities.split(",")))
    elif priority:
        q = q.filter(models.Ticket.priority == priority)
    if category:
        q = q.filter(models.Ticket.category == category)
    if unassigned:
        q = q.filter(models.Ticket.assigned_to_id == None)
    elif assigned_to_id is not None:
        q = q.filter(models.Ticket.assigned_to_id == assigned_to_id)
    if full_text:
        term = f"%{full_text}%"
        q = q.filter(
            models.Ticket.title.ilike(term) | models.Ticket.description.ilike(term)
        )
    elif search:
        q = q.filter(models.Ticket.title.ilike(f"%{search}%"))
    if date_from:
        q = q.filter(models.Ticket.created_at >= date_from)
    if date_to:
        q = q.filter(models.Ticket.created_at <= date_to + " 23:59:59")
    return q.order_by(models.Ticket.created_at.desc()).all()


@router.post("/", response_model=schemas.TicketDetailOut, status_code=201)
def create_ticket(
    ticket_in: schemas.TicketCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if ticket_in.type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="Type invalide")
    if ticket_in.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Catégorie invalide")

    # Priorité automatique si non spécifiée ou laissée à "normale" (valeur par défaut)
    auto_priority = suggest_priority(ticket_in.type)
    final_priority = ticket_in.priority if ticket_in.priority != "normale" else auto_priority

    if final_priority not in VALID_PRIORITIES:
        raise HTTPException(status_code=400, detail="Priorité invalide")

    ticket = models.Ticket(
        title=ticket_in.title,
        description=ticket_in.description,
        type=ticket_in.type,
        category=ticket_in.category,
        priority=final_priority,
        created_by_id=current_user.id,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    _record_history(db, ticket.id, current_user.id, "création", None, "ouvert")
    db.commit()
    db.refresh(ticket)
    broadcaster.broadcast_sync({
        "type": "ticket_created",
        "message": f"Nouveau ticket #{ticket.id} : {ticket.title}",
        "ticket_id": ticket.id,
        "by": current_user.username,
    })
    return ticket


@router.get("/timeline")
def get_timeline(
    days: int = Query(30, ge=7, le=90),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    since = datetime.utcnow() - timedelta(days=days)

    created_rows = db.query(
        func.date(models.Ticket.created_at).label("d"),
        func.count(models.Ticket.id).label("n")
    ).filter(models.Ticket.created_at >= since).group_by("d").all()

    resolved_rows = db.query(
        func.date(models.TicketHistory.changed_at).label("d"),
        func.count(models.TicketHistory.id).label("n")
    ).filter(
        models.TicketHistory.changed_at >= since,
        models.TicketHistory.field_changed == "statut",
        models.TicketHistory.new_value.in_(["resolu", "ferme"])
    ).group_by("d").all()

    created_map  = {str(r.d): r.n for r in created_rows}
    resolved_map = {str(r.d): r.n for r in resolved_rows}

    dates, created, resolved = [], [], []
    for i in range(days):
        d = (datetime.utcnow() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        dates.append(d)
        created.append(created_map.get(d, 0))
        resolved.append(resolved_map.get(d, 0))

    return {"dates": dates, "created": created, "resolved": resolved}


@router.get("/export")
def export_tickets(
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    type_group: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    assigned_to_id: Optional[int] = Query(None),
    unassigned: bool = Query(False),
    mine: bool = Query(False),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    q = db.query(models.Ticket)
    if mine:
        q = q.filter(models.Ticket.created_by_id == current_user.id)
    if status:
        q = q.filter(models.Ticket.status == status)
    if type:
        q = q.filter(models.Ticket.type == type)
    if type_group == "incident":
        q = q.filter(models.Ticket.type.in_(INCIDENT_TYPES))
    elif type_group == "demande":
        q = q.filter(models.Ticket.type.in_(DEMANDE_TYPES))
    if priority:
        q = q.filter(models.Ticket.priority == priority)
    if category:
        q = q.filter(models.Ticket.category == category)
    if unassigned:
        q = q.filter(models.Ticket.assigned_to_id == None)
    elif assigned_to_id is not None:
        q = q.filter(models.Ticket.assigned_to_id == assigned_to_id)
    if search:
        q = q.filter(models.Ticket.title.ilike(f"%{search}%"))
    tickets = q.order_by(models.Ticket.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["ID", "Titre", "Type", "Catégorie", "Priorité", "Statut",
                     "Créateur", "Assigné à", "Nb commentaires", "Date création", "Dernière MAJ"])
    for t in tickets:
        writer.writerow([
            t.id, t.title, t.type, t.category, t.priority, t.status,
            t.creator.username,
            t.assignee.username if t.assignee else "",
            len(t.comments),
            t.created_at.strftime("%d/%m/%Y %H:%M") if t.created_at else "",
            t.updated_at.strftime("%d/%m/%Y %H:%M") if t.updated_at else "",
        ])

    filename = f"tickets_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),  # utf-8-sig = BOM pour Excel
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/catalogue/pdf")
def export_catalogue_pdf(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.enums import TA_CENTER

    all_tickets = db.query(models.Ticket).all()
    by_type = {}
    for t in all_tickets:
        by_type[t.type] = by_type.get(t.type, 0) + 1

    INCIDENT_TYPES_LIST = [
        ("incident",               "Incident",               "normale",   24),
        ("panne",                  "Panne",                  "haute",      8),
        ("dysfonctionnement",      "Dysfonctionnement",      "normale",   24),
        ("alerte_securite",        "Alerte sécurité",        "critique",   4),
        ("coupure_reseau",         "Coupure réseau",         "haute",      8),
        ("intrusion",              "Intrusion",              "critique",   4),
        ("perte_donnees",          "Perte de données",       "critique",   4),
        ("surcharge_systeme",      "Surcharge système",      "haute",      8),
        ("panne_electrique",       "Panne électrique",       "haute",      8),
        ("virus",                  "Virus / Malware",        "critique",   4),
        ("phishing",               "Phishing / Spam",        "haute",      8),
        ("crash_application",      "Crash application",      "normale",   24),
        ("corruption_donnees",     "Corruption de données",  "critique",   4),
        ("indisponibilite_service","Indisponibilité service","haute",      8),
        ("acces_refuse",           "Accès refusé",           "normale",   24),
        ("ransomware",             "Ransomware / Chiffrement","critique",   4),
        ("fuite_donnees",          "Fuite de données",        "critique",   4),
        ("defaillance_serveur",    "Défaillance serveur",     "critique",   4),
        ("erreur_reseau",          "Erreur réseau / DNS",     "haute",      8),
        ("vol_equipement",         "Vol d'équipement",        "haute",      8),
        ("coupure_telephonie",     "Coupure téléphonie",      "haute",      8),
        ("ecran_bleu",             "Écran bleu (BSOD)",       "normale",   24),
        ("peripherique_defaillant","Périphérique défaillant", "normale",   24),
        ("spam_massif",            "Spam / Messagerie compromise","normale",24),
        ("probleme_impression",    "Problème d'impression",   "faible",    72),
        ("lenteur_systeme",        "Lenteur système / PC",    "haute",      8),
        ("mise_a_jour_echouee",    "Mise à jour échouée",     "normale",   24),
        ("certificat_expire",      "Certificat expiré (SSL/TLS)","haute",   8),
        ("sauvegarde_echouee",     "Échec de sauvegarde",     "haute",      8),
        ("attaque_ddos",           "Attaque DDoS",            "critique",   4),
        ("acces_non_autorise",     "Accès non autorisé / Compte piraté","critique",4),
        ("perte_connexion_wifi",   "Perte connexion Wi-Fi",   "normale",   24),
        ("messagerie_indisponible","Messagerie indisponible",  "haute",      8),
        ("partage_reseau_inaccessible","Partage réseau inaccessible","normale",24),
        ("application_lente",      "Application lente / plantée","normale",24),
        ("ecran_noir",             "Écran noir / sans signal", "normale",   24),
        ("clavier_souris_defaillant","Clavier ou souris défaillant","faible",72),
        ("son_defaillant",         "Problème son / audio",    "faible",    72),
        ("logiciel_non_autorise",  "Logiciel non autorisé détecté","haute",  8),
        ("erreur_connexion_vpn",   "Erreur connexion VPN",    "normale",   24),
        ("synchronisation_echouee","Échec synchronisation (AD/cloud)","normale",24),
        ("onduleur_defaillant",    "Défaillance onduleur (UPS)","haute",    8),
        ("stockage_plein",         "Disque / stockage plein", "haute",      8),
        ("usurpation_identite",    "Usurpation d'identité",   "critique",   4),
        ("base_donnees_corrompue", "Base de données corrompue","critique",   4),
        ("incompatibilite_logicielle","Incompatibilité logicielle","normale",24),
        ("camera_defaillante",     "Caméra / webcam défaillante","faible",  72),
        ("perte_connexion_internet","Perte connexion Internet","haute",      8),
        ("interruption_cloud",     "Interruption service cloud","haute",     8),
        ("erreur_authentification","Erreur d'authentification","normale",   24),
    ]
    DEMANDE_TYPES_LIST = [
        ("demande",                     "Demande générale",            "faible", 72),
        ("demande_acces",               "Accès",                       "faible", 72),
        ("demande_installation",        "Installation",                "faible", 72),
        ("demande_materiel",            "Matériel",                    "faible", 72),
        ("demande_information",         "Information",                 "faible", 72),
        ("demande_formation",           "Formation",                   "faible", 72),
        ("demande_sauvegarde",          "Sauvegarde",                  "faible", 72),
        ("demande_demenagement",        "Déménagement",                "faible", 72),
        ("demande_licence",             "Licence",                     "faible", 72),
        ("demande_reinitialisation_mdp","Réinitialisation mot de passe","faible",72),
        ("demande_creation_compte",     "Création de compte",          "faible", 72),
        ("demande_assistance",          "Assistance à distance",       "faible", 72),
        ("demande_configuration",       "Configuration",               "faible", 72),
        ("demande_mise_a_jour",         "Mise à jour logicielle",      "faible", 72),
        ("demande_archivage",           "Archivage de données",        "faible", 72),
        ("demande_deblockage_compte",   "Déblocage de compte",         "faible", 72),
        ("demande_vpn",                 "Accès VPN",                   "faible", 72),
        ("demande_messagerie",          "Messagerie / Email",          "faible", 72),
        ("demande_impression_config",   "Config. impression",          "faible", 72),
        ("demande_badge_acces",         "Badge d'accès physique",      "faible", 72),
        ("demande_onboarding",          "Onboarding nouvel employé",   "normale",24),
        ("demande_offboarding",         "Offboarding / Départ",        "normale",24),
        ("demande_audit_securite",      "Audit de sécurité",           "faible", 72),
        ("demande_intervention_site",   "Intervention sur site",       "normale",24),
        ("demande_certificat_ssl",      "Certificat SSL / PKI",        "normale",24),
        ("demande_extension_stockage",  "Extension de stockage",       "faible", 72),
        ("demande_redirection_mail",    "Redirection / alias email",   "faible", 72),
        ("demande_groupe_securite",     "Groupe de sécurité (AD)",     "faible", 72),
        ("demande_partage_reseau",      "Partage réseau (dossier partagé)", "faible", 72),
        ("demande_restauration",        "Restauration de données",     "normale",24),
        ("demande_tele_travail",        "Équipement télétravail",      "faible", 72),
        ("demande_poste_remplacement",  "Remplacement de poste",       "normale",24),
        ("demande_mise_en_service",     "Mise en service matériel",    "normale",24),
        ("demande_chiffrement",         "Chiffrement de poste / données","normale",24),
        ("demande_double_authentification","Activation 2FA / MFA",     "faible", 72),
        ("demande_revision_droits",     "Révision des droits d'accès", "normale",24),
        ("demande_telephone_ip",        "Téléphone IP / VoIP",         "faible", 72),
        ("demande_nettoyage_poste",     "Nettoyage / optimisation poste","faible",72),
        ("demande_migration_donnees",   "Migration de données",        "normale",24),
        ("demande_formation_securite",  "Formation cybersécurité",     "faible", 72),
        ("demande_mise_a_jour_firmware","Mise à jour firmware",        "faible", 72),
        ("demande_salle_reunion",       "Équipement salle de réunion", "faible", 72),
        ("demande_signature_mail",      "Configuration signature email","faible", 72),
        ("demande_rapport_activite",    "Rapport / extraction de données","faible",72),
        ("demande_antivirus",           "Installation / MAJ antivirus","faible", 72),
        ("demande_scan_securite",       "Scan de sécurité / vulnérabilités","normale",24),
        ("demande_connexion_bureau_distant","Connexion bureau à distance","faible",72),
        ("demande_acces_applicatif",    "Accès applicatif (ERP/CRM…)", "faible", 72),
        ("demande_supervision",         "Supervision / monitoring",    "faible", 72),
        ("demande_changement_mdp",      "Changement de mot de passe planifié","faible",72),
    ]
    PRIORITY_LABELS = {"critique": "Critique", "haute": "Haute", "normale": "Normale", "faible": "Faible"}
    PRIORITY_COLORS = {
        "critique": colors.HexColor("#c62828"),
        "haute":    colors.HexColor("#f57c00"),
        "normale":  colors.HexColor("#1976d2"),
        "faible":   colors.HexColor("#388e3c"),
    }
    PRIORITY_HEX = {
        "critique": "#c62828",
        "haute":    "#f57c00",
        "normale":  "#1976d2",
        "faible":   "#388e3c",
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    title_style   = ParagraphStyle("t", fontSize=20, fontName="Helvetica-Bold",
                                   textColor=colors.HexColor("#1565c0"), spaceAfter=4, alignment=TA_CENTER)
    sub_style     = ParagraphStyle("s", fontSize=10, fontName="Helvetica",
                                   textColor=colors.HexColor("#757575"), spaceAfter=16, alignment=TA_CENTER)
    section_style = ParagraphStyle("sec", fontSize=13, fontName="Helvetica-Bold",
                                   textColor=colors.white, spaceAfter=0)
    cell_style    = ParagraphStyle("c", fontSize=9, fontName="Helvetica", leading=12)
    count_style   = ParagraphStyle("n", fontSize=9, fontName="Helvetica-Bold",
                                   alignment=TA_CENTER)

    elements = [
        Paragraph("Catalogue des types de tickets", title_style),
        Paragraph(
            f"HelpDesk IT  •  Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}"
            f"  •  {current_user.username}",
            sub_style,
        ),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e0e0e0"), spaceAfter=16),
    ]

    headers_row = ["Type interne", "Libellé", "Priorité suggérée", "Délai SLA", "Tickets"]
    col_widths  = [3.8*cm, 5*cm, 3.5*cm, 2.5*cm, 2.5*cm]

    def build_section(title, bg_color, type_list):
        elements.append(Spacer(1, 8))
        # Section header as single-cell table for background color
        hdr_table = Table(
            [[Paragraph(title, section_style)]],
            colWidths=[sum(col_widths)],
        )
        hdr_table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), bg_color),
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
        ]))
        elements.append(hdr_table)

        data = [headers_row]
        row_cmds = []
        for i, (ttype, label, priority, sla_h) in enumerate(type_list, start=1):
            count = by_type.get(ttype, 0)
            prio_color = PRIORITY_COLORS[priority]
            data.append([
                Paragraph(f"<font color='#616161'>{ttype}</font>", cell_style),
                Paragraph(f"<b>{label}</b>", cell_style),
                Paragraph(f"<b><font color='{PRIORITY_HEX[priority]}'>{PRIORITY_LABELS[priority]}</font></b>", cell_style),
                Paragraph(f"{sla_h}h", cell_style),
                Paragraph(str(count), count_style),
            ])
            if i % 2 == 0:
                row_cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fafafa")))

        tbl = Table(data, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#eceff1")),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#e0e0e0")),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("ALIGN",         (4, 0), (4, -1), "CENTER"),
        ] + row_cmds))
        elements.append(tbl)

    build_section("INCIDENTS", colors.HexColor("#c62828"), INCIDENT_TYPES_LIST)
    build_section("DEMANDES",  colors.HexColor("#1565c0"), DEMANDE_TYPES_LIST)

    doc.build(elements)
    buf.seek(0)
    filename = f"catalogue_types_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/docs/pdf")
def export_documentation_pdf(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
                                    Table, TableStyle, PageBreak)
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2.5*cm, rightMargin=2.5*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    BLUE     = colors.HexColor("#1565c0")
    LBLUE    = colors.HexColor("#e3f2fd")
    DBLUE    = colors.HexColor("#0d47a1")
    GREY     = colors.HexColor("#757575")
    LGREY    = colors.HexColor("#f5f5f5")
    GREEN    = colors.HexColor("#2e7d32")
    ORANGE   = colors.HexColor("#e65100")
    RED      = colors.HexColor("#c62828")

    h_cover  = ParagraphStyle("hcover",  fontSize=28, fontName="Helvetica-Bold", textColor=BLUE,  alignment=TA_CENTER, spaceAfter=8)
    h_sub    = ParagraphStyle("hsub",    fontSize=13, fontName="Helvetica",      textColor=GREY,  alignment=TA_CENTER, spaceAfter=4)
    h_date   = ParagraphStyle("hdate",   fontSize=10, fontName="Helvetica",      textColor=GREY,  alignment=TA_CENTER, spaceAfter=30)
    h1       = ParagraphStyle("h1",      fontSize=16, fontName="Helvetica-Bold", textColor=BLUE,  spaceBefore=18, spaceAfter=6)
    h2       = ParagraphStyle("h2",      fontSize=12, fontName="Helvetica-Bold", textColor=DBLUE, spaceBefore=12, spaceAfter=4)
    body     = ParagraphStyle("body",    fontSize=10, fontName="Helvetica",      leading=15,     alignment=TA_JUSTIFY, spaceAfter=6)
    bullet   = ParagraphStyle("bullet",  fontSize=10, fontName="Helvetica",      leading=14,     leftIndent=16, spaceAfter=3)
    note     = ParagraphStyle("note",    fontSize=9,  fontName="Helvetica-Oblique", textColor=GREY, spaceAfter=6)
    code_sty = ParagraphStyle("code",    fontSize=9,  fontName="Courier",        leading=13,     leftIndent=12,
                               backColor=LGREY, borderPadding=6, spaceAfter=8)

    def h_rule():
        return HRFlowable(width="100%", thickness=1, color=colors.HexColor("#bbdefb"), spaceAfter=8)

    def section_header(title, color=BLUE):
        tbl = Table([[Paragraph(title, ParagraphStyle("sh", fontSize=12, fontName="Helvetica-Bold",
                                                       textColor=colors.white))]], colWidths=[15*cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), color),
            ("TOPPADDING",    (0,0),(-1,-1), 6),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
            ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ]))
        return tbl

    def badge_table(items):
        data = []
        for label, val, col in items:
            data.append([
                Paragraph(f"<b>{label}</b>",
                          ParagraphStyle("bl", fontSize=9, fontName="Helvetica")),
                Paragraph(val, ParagraphStyle("bv", fontSize=9, fontName="Helvetica",
                                              textColor=col)),
            ])
        tbl = Table(data, colWidths=[5*cm, 10*cm])
        tbl.setStyle(TableStyle([
            ("GRID",       (0,0),(-1,-1), 0.4, colors.HexColor("#e0e0e0")),
            ("BACKGROUND", (0,0),(0,-1),  LGREY),
            ("VALIGN",     (0,0),(-1,-1), "MIDDLE"),
            ("TOPPADDING", (0,0),(-1,-1), 4),
            ("BOTTOMPADDING",(0,0),(-1,-1),4),
            ("LEFTPADDING",(0,0),(-1,-1), 6),
        ]))
        return tbl

    elems = []

    # ── Cover page ──────────────────────────────────────────────
    elems += [
        Spacer(1, 3*cm),
        Paragraph("HelpDesk IT", h_cover),
        Paragraph("Documentation d'installation et d'utilisation", h_sub),
        Spacer(1, 0.5*cm),
        HRFlowable(width="60%", thickness=2, color=BLUE, hAlign="CENTER", spaceAfter=16),
        Paragraph(f"Version 1.0  •  Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}", h_date),
        Spacer(1, 1*cm),
        badge_table([
            ("Application", "HelpDesk IT — Système de ticketing", BLUE),
            ("Version",     "1.0.0", GREEN),
            ("API",         "FastAPI (Python 3.10+)", GREY),
            ("Base de données", "SQLite (développement) / PostgreSQL (prod)", GREY),
            ("Interface",   "Navigateur web — Bootstrap 5", GREY),
        ]),
        PageBreak(),
    ]

    # ── Table of contents (manual) ───────────────────────────────
    toc_style = ParagraphStyle("toc", fontSize=11, fontName="Helvetica", leading=20, leftIndent=10)
    toc_sub   = ParagraphStyle("tocs", fontSize=10, fontName="Helvetica", leading=18, leftIndent=28, textColor=GREY)
    elems += [
        Paragraph("Table des matières", h1),
        h_rule(),
        Paragraph("1.  Installation", toc_style),
        Paragraph("1.1  Prérequis système", toc_sub),
        Paragraph("1.2  Installation depuis les sources", toc_sub),
        Paragraph("1.3  Installation depuis l'installateur MSI (Windows)", toc_sub),
        Paragraph("1.4  Configuration de l'environnement", toc_sub),
        Paragraph("2.  Démarrage rapide", toc_style),
        Paragraph("2.1  Lancement du serveur", toc_sub),
        Paragraph("2.2  Premier accès — créer un compte administrateur", toc_sub),
        Paragraph("3.  Guide utilisateur", toc_style),
        Paragraph("3.1  Connexion et tableau de bord", toc_sub),
        Paragraph("3.2  Créer un ticket", toc_sub),
        Paragraph("3.3  Suivre ses tickets", toc_sub),
        Paragraph("3.4  Base de connaissances", toc_sub),
        Paragraph("4.  Guide technicien", toc_style),
        Paragraph("4.1  Vue d'ensemble des tickets", toc_sub),
        Paragraph("4.2  Assigner et mettre à jour un ticket", toc_sub),
        Paragraph("4.3  Tableau Kanban", toc_sub),
        Paragraph("4.4  SLA et escalades automatiques", toc_sub),
        Paragraph("5.  Guide administrateur", toc_style),
        Paragraph("5.1  Gestion des utilisateurs", toc_sub),
        Paragraph("5.2  Rapports et statistiques", toc_sub),
        Paragraph("5.3  Exports CSV et PDF", toc_sub),
        PageBreak(),
    ]

    # ── Chapter 1 — Installation ─────────────────────────────────
    elems += [
        Paragraph("1. Installation", h1),
        h_rule(),
        section_header("1.1  Prérequis système"),
        Spacer(1, 6),
        badge_table([
            ("Système d'exploitation", "Windows 10/11, Linux (Ubuntu 20.04+), macOS 12+", GREY),
            ("Python",                "3.10 ou supérieur", GREEN),
            ("Espace disque",         "Minimum 200 Mo", GREY),
            ("RAM",                   "Minimum 512 Mo recommandés", GREY),
            ("Navigateur",            "Chrome, Firefox, Edge (version récente)", GREY),
        ]),
        Spacer(1, 10),
        section_header("1.2  Installation depuis les sources"),
        Spacer(1, 6),
        Paragraph("Cloner le dépôt et installer les dépendances :", body),
        Paragraph("git clone https://github.com/votre-org/helpdesk-it.git", code_sty),
        Paragraph("cd helpdesk-it", code_sty),
        Paragraph("pip install -r requirements.txt", code_sty),
        Paragraph(
            "Les dépendances principales sont : <b>fastapi</b>, <b>uvicorn</b>, <b>sqlalchemy</b>, "
            "<b>python-jose</b>, <b>passlib[bcrypt]</b>, <b>reportlab</b>.",
            body),
        Spacer(1, 10),
        section_header("1.3  Installation depuis l'installateur MSI (Windows)"),
        Spacer(1, 6),
        Paragraph(
            "Un installateur <b>HelpDesk_IT_Setup.msi</b> est disponible pour Windows. "
            "Double-cliquez sur le fichier et suivez l'assistant d'installation. "
            "L'application est installée dans <i>C:\\Program Files\\HelpDesk IT\\</i> "
            "et un raccourci est créé sur le bureau.", body),
        Paragraph("Pour désinstaller, utilisez le Panneau de configuration → Programmes → Désinstaller.", note),
        Spacer(1, 10),
        section_header("1.4  Configuration de l'environnement"),
        Spacer(1, 6),
        Paragraph("Deux variables d'environnement optionnelles permettent de personnaliser le déploiement :", body),
        badge_table([
            ("HELPDESK_DB_PATH",     "Chemin vers le fichier SQLite (défaut : ./ticketing.db)", GREY),
            ("HELPDESK_STATIC_PATH", "Répertoire des fichiers statiques (défaut : static/)", GREY),
        ]),
        Spacer(1, 6),
        Paragraph("Exemple sous Linux/macOS :", body),
        Paragraph("export HELPDESK_DB_PATH=/var/data/helpdesk.db", code_sty),
        Paragraph("Exemple sous Windows (PowerShell) :", body),
        Paragraph("$env:HELPDESK_DB_PATH = 'C:\\Data\\helpdesk.db'", code_sty),
        PageBreak(),
    ]

    # ── Chapter 2 — Démarrage rapide ─────────────────────────────
    elems += [
        Paragraph("2. Démarrage rapide", h1),
        h_rule(),
        section_header("2.1  Lancement du serveur"),
        Spacer(1, 6),
        Paragraph("Depuis le répertoire du projet :", body),
        Paragraph("uvicorn main:app --reload --port 8000", code_sty),
        Paragraph(
            "L'application est accessible à l'adresse <b>http://localhost:8000</b>. "
            "L'option <code>--reload</code> redémarre automatiquement le serveur lors de modifications "
            "de fichiers (à utiliser uniquement en développement).", body),
        Spacer(1, 10),
        section_header("2.2  Premier accès — créer un compte administrateur"),
        Spacer(1, 6),
        Paragraph(
            "Au premier lancement, la base de données est vide. "
            "Utilisez le script <b>seed.py</b> pour créer des données de démonstration :", body),
        Paragraph("python seed.py", code_sty),
        Paragraph(
            "Pour créer manuellement un compte administrateur, appelez l'API d'inscription "
            "puis modifiez manuellement le rôle dans la base de données, "
            "ou utilisez un client HTTP (curl, Postman) :", body),
        Paragraph(
            'curl -X POST http://localhost:8000/api/auth/register \\\n'
            '  -H "Content-Type: application/json" \\\n'
            '  -d \'{"username":"admin","email":"admin@example.com","password":"motdepasse"}\'',
            code_sty),
        PageBreak(),
    ]

    # ── Chapter 3 — Guide utilisateur ────────────────────────────
    elems += [
        Paragraph("3. Guide utilisateur", h1),
        h_rule(),
        section_header("3.1  Connexion et tableau de bord", GREEN),
        Spacer(1, 6),
        Paragraph(
            "Ouvrez votre navigateur et accédez à l'URL du serveur HelpDesk. "
            "Saisissez votre identifiant et votre mot de passe. "
            "Après connexion, le <b>tableau de bord</b> affiche :", body),
        Paragraph("• Les compteurs de tickets (ouverts, en cours, résolus, fermés)", bullet),
        Paragraph("• La distribution par priorité et par catégorie", bullet),
        Paragraph("• Le graphique d'activité sur les 30 derniers jours", bullet),
        Paragraph("• Vos tickets personnels et les tickets qui vous sont assignés", bullet),
        Spacer(1, 10),
        section_header("3.2  Créer un ticket", GREEN),
        Spacer(1, 6),
        Paragraph(
            "Cliquez sur le bouton <b>+ Nouveau ticket</b> dans la barre de navigation. "
            "Remplissez les champs :", body),
        badge_table([
            ("Titre",       "Résumé court du problème (obligatoire)", RED),
            ("Description", "Détails du problème ou de la demande (obligatoire)", RED),
            ("Type",        "Sélectionnez le type parmi les 40 types disponibles", GREY),
            ("Catégorie",   "Matériel, Logiciel, Réseau, Sécurité, Téléphonie, Imprimante, Autre", GREY),
            ("Priorité",    "Faible, Normale, Haute, Critique — suggérée automatiquement selon le type", GREY),
        ]),
        Paragraph(
            "La priorité est automatiquement suggérée selon le type de ticket sélectionné. "
            "Vous pouvez la modifier manuellement.", note),
        Spacer(1, 10),
        section_header("3.3  Suivre ses tickets", GREEN),
        Spacer(1, 6),
        Paragraph(
            "Dans le menu <b>Mes tickets</b>, vous visualisez tous vos tickets créés. "
            "Cliquez sur une ligne pour ouvrir le détail : description complète, "
            "historique des modifications, commentaires.", body),
        Paragraph(
            "Vous pouvez ajouter un commentaire depuis le panneau de détail. "
            "Les changements de statut et d'assignation sont tracés automatiquement.", body),
        Spacer(1, 10),
        section_header("3.4  Base de connaissances", GREEN),
        Spacer(1, 6),
        Paragraph(
            "La section <b>Base de connaissances</b> regroupe des articles rédigés par les techniciens. "
            "Vous pouvez rechercher un article par mot-clé, filtrer par type de ticket ou catégorie. "
            "Les articles supportent la mise en forme Markdown.", body),
        PageBreak(),
    ]

    # ── Chapter 4 — Guide technicien ─────────────────────────────
    elems += [
        Paragraph("4. Guide technicien", h1),
        h_rule(),
        section_header("4.1  Vue d'ensemble des tickets", ORANGE),
        Spacer(1, 6),
        Paragraph(
            "Le menu <b>Tous les tickets</b> affiche l'ensemble des tickets du système. "
            "Des filtres permettent de trier par statut, type, priorité, catégorie, "
            "technicien assigné et recherche textuelle.", body),
        Paragraph(
            "Les vues <b>Incidents</b> et <b>Demandes</b> permettent de se concentrer "
            "sur chaque groupe avec des filtres dédiés et des exports CSV/PDF.", body),
        Spacer(1, 10),
        section_header("4.2  Assigner et mettre à jour un ticket", ORANGE),
        Spacer(1, 6),
        Paragraph(
            "Cliquez sur un ticket pour ouvrir le panneau de détail. "
            "En tant que technicien ou administrateur, vous pouvez :", body),
        Paragraph("• Changer le statut : Ouvert → En cours → Résolu → Fermé", bullet),
        Paragraph("• Modifier la priorité (escalade manuelle)", bullet),
        Paragraph("• Assigner le ticket à un technicien", bullet),
        Paragraph("• Ajouter un commentaire visible par le demandeur", bullet),
        Paragraph(
            "Chaque modification est enregistrée dans l'<b>historique</b> du ticket "
            "avec la date et l'auteur.", note),
        Spacer(1, 10),
        section_header("4.3  Tableau Kanban", ORANGE),
        Spacer(1, 6),
        Paragraph(
            "La vue <b>Kanban</b> affiche les tickets ouverts et en cours dans des colonnes "
            "par statut. Glissez-déposez un ticket d'une colonne à l'autre pour changer son statut. "
            "Utilisez les filtres de priorité et catégorie pour réduire l'affichage.", body),
        Spacer(1, 10),
        section_header("4.4  SLA et escalades automatiques", ORANGE),
        Spacer(1, 6),
        Paragraph(
            "La vue <b>SLA</b> liste les tickets ouverts classés par urgence SLA :", body),
        badge_table([
            ("Critique", "SLA : 4 heures",   RED),
            ("Haute",    "SLA : 8 heures",   ORANGE),
            ("Normale",  "SLA : 24 heures",  BLUE),
            ("Faible",   "SLA : 72 heures",  GREEN),
        ]),
        Paragraph(
            "Un moteur d'escalade automatique vérifie toutes les heures les tickets non résolus "
            "et élève leur priorité si le délai SLA est dépassé. "
            "L'escalade est consignée dans l'historique du ticket.", body),
        PageBreak(),
    ]

    # ── Chapter 5 — Guide administrateur ─────────────────────────
    elems += [
        Paragraph("5. Guide administrateur", h1),
        h_rule(),
        section_header("5.1  Gestion des utilisateurs", RED),
        Spacer(1, 6),
        Paragraph(
            "La section <b>Administration</b> (accessible aux administrateurs uniquement) "
            "liste tous les comptes utilisateurs. Vous pouvez :", body),
        Paragraph("• Modifier le rôle d'un utilisateur : Utilisateur / Technicien / Administrateur", bullet),
        Paragraph("• Voir les informations de profil et la date d'inscription", bullet),
        Paragraph(
            "Les rôles disponibles définissent les permissions :", body),
        badge_table([
            ("Utilisateur",    "Créer ses propres tickets, ajouter des commentaires", GREY),
            ("Technicien",     "Tout utilisateur + assigner, changer statut/priorité, rédiger KB", ORANGE),
            ("Administrateur", "Tout technicien + gérer les utilisateurs, supprimer des tickets", RED),
        ]),
        Spacer(1, 10),
        section_header("5.2  Rapports et statistiques", RED),
        Spacer(1, 6),
        Paragraph(
            "La vue <b>Rapports</b> présente :", body),
        Paragraph("• Le taux de résolution global (tickets résolus / total)", bullet),
        Paragraph("• Le temps moyen de résolution par priorité (en heures)", bullet),
        Paragraph("• Le top 8 des techniciens les plus actifs", bullet),
        Paragraph("• Le graphique chronologique des tickets créés vs résolus (7 à 90 jours)", bullet),
        Spacer(1, 10),
        section_header("5.3  Exports CSV et PDF", RED),
        Spacer(1, 6),
        Paragraph(
            "Des boutons d'export sont disponibles dans les vues "
            "<b>Tous les tickets</b>, <b>Mes tickets</b>, <b>Incidents</b> et <b>Demandes</b>. "
            "Les filtres actifs sont appliqués à l'export.", body),
        badge_table([
            ("CSV",            "Export tableur compatible Excel (encodage UTF-8 BOM)", GREEN),
            ("PDF",            "Export mise en page professionnelle (paysage A4)", RED),
            ("Catalogue PDF",  "Liste complète des 40 types de tickets avec priorités et SLA", BLUE),
            ("Documentation",  "Ce document — guide complet d'installation et d'utilisation", GREY),
        ]),
        Spacer(1, 20),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e0e0e0"), spaceAfter=8),
        Paragraph(
            f"HelpDesk IT v1.0  •  Document généré automatiquement le "
            f"{datetime.now().strftime('%d/%m/%Y à %H:%M')}  •  {current_user.username}",
            ParagraphStyle("footer", fontSize=8, fontName="Helvetica", textColor=GREY, alignment=TA_CENTER)
        ),
    ]

    doc.build(elems)
    buf.seek(0)
    filename = f"helpdesk_documentation_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/install/pdf")
def export_install_procedure_pdf(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
                                    Table, TableStyle, PageBreak, ListFlowable, ListItem)
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2.5*cm, rightMargin=2.5*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    BLUE   = colors.HexColor("#1565c0")
    DBLUE  = colors.HexColor("#0d47a1")
    LBLUE  = colors.HexColor("#e3f2fd")
    GREY   = colors.HexColor("#757575")
    LGREY  = colors.HexColor("#f5f5f5")
    GREEN  = colors.HexColor("#2e7d32")
    LGREEN = colors.HexColor("#e8f5e9")
    ORANGE = colors.HexColor("#e65100")
    LORAN  = colors.HexColor("#fff3e0")
    RED    = colors.HexColor("#c62828")
    LRED   = colors.HexColor("#ffebee")
    WHITE  = colors.white
    BLACK  = colors.HexColor("#212121")

    def sty(name, **kw):
        return ParagraphStyle(name, **kw)

    h_cover  = sty("hcov", fontSize=30, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_CENTER, spaceAfter=6)
    h_sub    = sty("hsub", fontSize=13, fontName="Helvetica",      textColor=colors.HexColor("#bbdefb"), alignment=TA_CENTER, spaceAfter=4)
    h_date   = sty("hdat", fontSize=10, fontName="Helvetica",      textColor=colors.HexColor("#90caf9"), alignment=TA_CENTER, spaceAfter=30)
    h1       = sty("h1",   fontSize=16, fontName="Helvetica-Bold", textColor=BLUE, spaceBefore=20, spaceAfter=6)
    h2       = sty("h2",   fontSize=12, fontName="Helvetica-Bold", textColor=DBLUE, spaceBefore=12, spaceAfter=4)
    h3       = sty("h3",   fontSize=10, fontName="Helvetica-Bold", textColor=BLACK, spaceBefore=8, spaceAfter=3)
    body     = sty("bd",   fontSize=10, fontName="Helvetica",      leading=15, alignment=TA_JUSTIFY, spaceAfter=5)
    bullet   = sty("bu",   fontSize=10, fontName="Helvetica",      leading=14, leftIndent=18, spaceAfter=3)
    code_sty = sty("co",   fontSize=9,  fontName="Courier",        leading=13, leftIndent=10,
                   backColor=LGREY, borderPadding=6, spaceAfter=8)
    note_ok  = sty("nok",  fontSize=9,  fontName="Helvetica",      textColor=GREEN,  leftIndent=14, spaceAfter=4)
    note_warn= sty("nwa",  fontSize=9,  fontName="Helvetica",      textColor=ORANGE, leftIndent=14, spaceAfter=4)
    note_err = sty("ner",  fontSize=9,  fontName="Helvetica",      textColor=RED,    leftIndent=14, spaceAfter=4)
    toc_sty  = sty("toc",  fontSize=11, fontName="Helvetica",      leading=22, leftIndent=8)
    toc_sub  = sty("tocs", fontSize=10, fontName="Helvetica",      leading=18, leftIndent=26, textColor=GREY)

    def hr(): return HRFlowable(width="100%", thickness=1, color=colors.HexColor("#bbdefb"), spaceAfter=8)

    def section_hdr(title, bg=BLUE):
        t = Table([[Paragraph(title, sty("sh", fontSize=12, fontName="Helvetica-Bold", textColor=WHITE))]], colWidths=[15*cm])
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),("TOPPADDING",(0,0),(-1,-1),7),
                                ("BOTTOMPADDING",(0,0),(-1,-1),7),("LEFTPADDING",(0,0),(-1,-1),12)]))
        return t

    def step_box(n, title, content, color=LBLUE, border=BLUE):
        inner = [
            [Paragraph(f"<b>Étape {n}</b>", sty("sn", fontSize=9, fontName="Helvetica-Bold", textColor=border)),
             Paragraph(f"<b>{title}</b>", sty("st", fontSize=10, fontName="Helvetica-Bold", textColor=BLACK))],
            ["", Paragraph(content, body)],
        ]
        t = Table(inner, colWidths=[1.8*cm, 13.2*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0),(-1,-1), color),
            ("BOX",        (0,0),(-1,-1), 1, border),
            ("LINEAFTER",  (0,0),(0,-1),  1, border),
            ("VALIGN",     (0,0),(-1,-1), "TOP"),
            ("TOPPADDING", (0,0),(-1,-1), 6),("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",(0,0),(-1,-1), 8),("RIGHTPADDING",(0,0),(-1,-1),8),
            ("SPAN",       (0,1),(0,1)),
        ]))
        return t

    def alert(icon, text, bg, border):
        t = Table([[Paragraph(f"<b>{icon}  {text}</b>", sty("al", fontSize=9, fontName="Helvetica", textColor=border))]], colWidths=[15*cm])
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),("BOX",(0,0),(-1,-1),1,border),
                                ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
                                ("LEFTPADDING",(0,0),(-1,-1),10)]))
        return t

    def info_table(rows):
        data = [[Paragraph(f"<b>{k}</b>", sty("ik", fontSize=9, fontName="Helvetica")),
                 Paragraph(v, sty("iv", fontSize=9, fontName="Helvetica"))] for k,v in rows]
        t = Table(data, colWidths=[5*cm, 10*cm])
        t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#e0e0e0")),
                                ("BACKGROUND",(0,0),(0,-1),LGREY),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                                ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
                                ("LEFTPADDING",(0,0),(-1,-1),6)]))
        return t

    elems = []

    # ══ Page de couverture ═══════════════════════════════════════════════════
    cover_bg = Table(
        [[Paragraph("HelpDesk IT", h_cover)],
         [Paragraph("Procédure d'installation et de lancement", h_sub)],
         [Paragraph(f"Installation MSI  •  Windows 10 / 11", h_sub)],
         [Spacer(1, 0.3*cm)],
         [HRFlowable(width="50%", thickness=2, color=colors.HexColor("#90caf9"), hAlign="CENTER", spaceAfter=10)],
         [Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}  •  {current_user.username}", h_date)],
         [Spacer(1, 0.5*cm)],
         [info_table([
             ("Version",        "1.0.0"),
             ("Fichier",        "HelpDesk_IT_Setup.msi"),
             ("Système cible",  "Windows 10 (1903+) / Windows 11"),
             ("Architecture",   "x64"),
             ("Espace requis",  "≈ 120 Mo"),
             ("Droits requis",  "Administrateur local (installation), Utilisateur standard (lancement)"),
         ])],
        ],
        colWidths=[15*cm]
    )
    cover_bg.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(-1,-1), BLUE),
        ("TOPPADDING", (0,0),(-1,-1), 12),
        ("LEFTPADDING",(0,0),(-1,-1), 20),
        ("RIGHTPADDING",(0,0),(-1,-1),20),
        ("BOTTOMPADDING",(0,0),(-1,-1),20),
    ]))
    elems += [cover_bg, PageBreak()]

    # ══ Table des matières ════════════════════════════════════════════════════
    elems += [
        Paragraph("Table des matières", h1), hr(),
        Paragraph("1.  Prérequis système", toc_sty),
        Paragraph("2.  Obtenir le fichier MSI", toc_sty),
        Paragraph("3.  Installation pas à pas", toc_sty),
        Paragraph("3.1  Lancement de l'assistant", toc_sub),
        Paragraph("3.2  Acceptation de la licence", toc_sub),
        Paragraph("3.3  Choix du répertoire d'installation", toc_sub),
        Paragraph("3.4  Installation et création des raccourcis", toc_sub),
        Paragraph("3.5  Fin de l'assistant", toc_sub),
        Paragraph("4.  Premier lancement", toc_sty),
        Paragraph("4.1  Depuis le raccourci bureau", toc_sub),
        Paragraph("4.2  Depuis le menu Démarrer", toc_sub),
        Paragraph("4.3  Comportement au démarrage", toc_sub),
        Paragraph("5.  Accès à l'interface web", toc_sty),
        Paragraph("6.  Connexion et configuration initiale", toc_sty),
        Paragraph("6.1  Comptes par défaut", toc_sub),
        Paragraph("6.2  Changer le mot de passe administrateur", toc_sub),
        Paragraph("7.  Lancement en arrière-plan / au démarrage Windows", toc_sty),
        Paragraph("8.  Résolution des problèmes courants", toc_sty),
        Paragraph("9.  Désinstallation", toc_sty),
        PageBreak(),
    ]

    # ══ Chapitre 1 — Prérequis ════════════════════════════════════════════════
    elems += [
        Paragraph("1.  Prérequis système", h1), hr(),
        body and None or Spacer(1, 1),
        Paragraph(
            "Avant d'installer HelpDesk IT, vérifiez que votre poste remplit les conditions suivantes :", body),
        info_table([
            ("Système d'exploitation", "Windows 10 (version 1903 ou supérieure) ou Windows 11"),
            ("Architecture",          "64 bits (x64) — obligatoire"),
            ("RAM",                   "Minimum 512 Mo disponibles (1 Go recommandé)"),
            ("Espace disque",         "120 Mo pour l'installation + 50 Mo pour les données"),
            ("Droits",                "Compte <b>Administrateur local</b> pour l'installation"),
            ("Navigateur",            "Chrome 90+, Firefox 88+, Edge 90+ ou tout navigateur moderne"),
            ("Port réseau",           "Port TCP <b>8000</b> disponible sur 127.0.0.1 (localhost uniquement)"),
        ]),
        Spacer(1, 8),
        alert("ℹ️", "Aucune connexion Internet n'est requise. HelpDesk IT fonctionne entièrement en local.", LBLUE, BLUE),
        alert("⚠️", "Si le port 8000 est déjà utilisé, arrêtez l'application conflictuelle avant de lancer HelpDesk IT.", LORAN, ORANGE),
        PageBreak(),
    ]

    # ══ Chapitre 2 — Obtenir le MSI ══════════════════════════════════════════
    elems += [
        Paragraph("2.  Obtenir le fichier MSI", h1), hr(),
        Paragraph(
            "Le fichier <b>HelpDesk_IT_Setup.msi</b> peut être obtenu de deux façons :", body),
        Paragraph("<b>Option A — Depuis le référentiel de déploiement interne</b>", h3),
        Paragraph(
            "Contactez votre administrateur système ou téléchargez le fichier depuis le partage réseau "
            "ou l'intranet de votre organisation.", body),
        Paragraph("<b>Option B — Compilation depuis les sources</b>", h3),
        Paragraph("Si vous disposez des sources du projet, exécutez le script de build :", body),
        Paragraph("build_msi.bat", code_sty),
        Paragraph(
            "Ce script effectue automatiquement les étapes suivantes :", body),
        Paragraph("1. Vérifie et installe PyInstaller si absent", bullet),
        Paragraph("2. Vérifie la présence de WiX Toolset v3 (ouvre la page de téléchargement si absent)", bullet),
        Paragraph("3. Crée l'exécutable autonome avec PyInstaller", bullet),
        Paragraph("4. Génère le catalogue de fichiers (heat.exe)", bullet),
        Paragraph("5. Compile et lie le MSI (candle.exe + light.exe)", bullet),
        Paragraph(
            "À la fin du build, le fichier <b>HelpDesk_IT_Setup.msi</b> est créé à la racine du projet "
            "et la fenêtre Explorateur l'affiche automatiquement.", body),
        alert("ℹ️", "WiX Toolset v3 est requis pour le build. Téléchargez-le sur : https://github.com/wixtoolset/wix3/releases/latest", LBLUE, BLUE),
        PageBreak(),
    ]

    # ══ Chapitre 3 — Installation pas à pas ══════════════════════════════════
    elems += [
        Paragraph("3.  Installation pas à pas", h1), hr(),
        Paragraph(
            "L'installation se fait via un assistant graphique Windows Installer standard. "
            "Suivez les étapes ci-dessous.", body),
        Spacer(1, 6),
        section_hdr("3.1  Lancement de l'assistant"),
        Spacer(1, 6),
        step_box("1", "Localiser le fichier MSI",
            "Naviguez jusqu'au fichier <b>HelpDesk_IT_Setup.msi</b> dans l'Explorateur Windows."),
        Spacer(1, 4),
        step_box("2", "Exécuter en tant qu'administrateur",
            "Clic droit sur <b>HelpDesk_IT_Setup.msi</b> → <b>« Exécuter en tant qu'administrateur »</b>.<br/>"
            "Si le Contrôle de compte d'utilisateur (UAC) s'affiche, cliquez sur <b>Oui</b>."),
        Spacer(1, 4),
        step_box("3", "Écran d'accueil",
            "L'assistant d'installation s'ouvre. Cliquez sur <b>Suivant</b> pour commencer."),
        Spacer(1, 10),
        section_hdr("3.2  Acceptation de la licence"),
        Spacer(1, 6),
        step_box("4", "Contrat de licence",
            "Lisez le contrat de licence utilisateur final (CLUF).<br/>"
            "Sélectionnez <b>« J'accepte les termes de ce contrat de licence »</b>, puis cliquez sur <b>Suivant</b>."),
        Spacer(1, 10),
        section_hdr("3.3  Choix du répertoire d'installation"),
        Spacer(1, 6),
        step_box("5", "Répertoire d'installation",
            "Le répertoire par défaut est :<br/>"
            "<b>C:\\Program Files\\HelpDesk IT\\</b><br/><br/>"
            "Pour modifier ce chemin, cliquez sur <b>Parcourir…</b> et sélectionnez le dossier souhaité.<br/>"
            "Cliquez sur <b>Suivant</b> une fois le chemin défini."),
        Spacer(1, 4),
        alert("ℹ️", "Les données utilisateur (base de données) sont stockées séparément dans : "
              "%APPDATA%\\HelpDesk IT\\  — ce dossier est conservé lors d'une mise à jour.", LBLUE, BLUE),
        Spacer(1, 10),
        section_hdr("3.4  Installation et création des raccourcis"),
        Spacer(1, 6),
        step_box("6", "Lancer l'installation",
            "Cliquez sur <b>Installer</b> pour démarrer la copie des fichiers.<br/>"
            "Une barre de progression indique l'avancement. L'opération dure généralement <b>30 à 60 secondes</b>."),
        Spacer(1, 4),
        Paragraph("L'installateur crée automatiquement :", body),
        Paragraph("• Un raccourci <b>HelpDesk IT</b> sur le Bureau", bullet),
        Paragraph("• Un raccourci dans le menu <b>Démarrer → HelpDesk IT</b>", bullet),
        Paragraph("• Une entrée dans <b>Panneau de configuration → Programmes</b> pour la désinstallation", bullet),
        Spacer(1, 10),
        section_hdr("3.5  Fin de l'assistant"),
        Spacer(1, 6),
        step_box("7", "Terminer l'installation",
            "Une fois l'installation terminée, cliquez sur <b>Terminer</b>.<br/>"
            "L'application peut être lancée immédiatement depuis le raccourci bureau."),
        PageBreak(),
    ]

    # ══ Chapitre 4 — Premier lancement ════════════════════════════════════════
    elems += [
        Paragraph("4.  Premier lancement", h1), hr(),
        Spacer(1, 4),
        section_hdr("4.1  Depuis le raccourci bureau"),
        Spacer(1, 6),
        step_box("1", "Double-clic sur le raccourci",
            "Double-cliquez sur l'icône <b>HelpDesk IT</b> présente sur le Bureau.<br/>"
            "Une fenêtre de console peut apparaître brièvement — c'est normal, le serveur démarre."),
        Spacer(1, 10),
        section_hdr("4.2  Depuis le menu Démarrer"),
        Spacer(1, 6),
        step_box("2", "Menu Démarrer",
            "Cliquez sur <b>Démarrer (⊞)</b> → tapez <b>HelpDesk IT</b> → cliquez sur l'application."),
        Spacer(1, 10),
        section_hdr("4.3  Comportement au démarrage"),
        Spacer(1, 6),
        Paragraph("Au lancement, l'application effectue les opérations suivantes :", body),
        info_table([
            ("1. Initialisation",    "Le serveur FastAPI/uvicorn démarre sur <b>127.0.0.1:8000</b>"),
            ("2. Base de données",   "La base SQLite est créée dans <b>%APPDATA%\\HelpDesk IT\\helpdesk.db</b> si elle n'existe pas"),
            ("3. Attente serveur",   "L'application attend jusqu'à 30 secondes que le serveur réponde"),
            ("4. Ouverture navigateur", "Le navigateur par défaut s'ouvre automatiquement sur <b>http://127.0.0.1:8000</b>"),
        ]),
        Spacer(1, 8),
        alert("✅", "Le délai de démarrage habituel est de 3 à 8 secondes selon les performances du poste.", LGREEN, GREEN),
        alert("⚠️", "Ne fermez pas la fenêtre de console : elle héberge le serveur. "
              "La fermer arrête l'application.", LORAN, ORANGE),
        PageBreak(),
    ]

    # ══ Chapitre 5 — Accès à l'interface ═════════════════════════════════════
    elems += [
        Paragraph("5.  Accès à l'interface web", h1), hr(),
        Paragraph(
            "HelpDesk IT est une application web accessible depuis n'importe quel navigateur "
            "installé sur le poste :", body),
        info_table([
            ("URL locale",      "<b>http://127.0.0.1:8000</b>  ou  <b>http://localhost:8000</b>"),
            ("Navigateurs",     "Chrome, Firefox, Edge, Opera (versions récentes)"),
            ("Accès réseau",    "Par défaut, l'accès est limité à la machine locale (127.0.0.1)"),
            ("HTTPS",           "Non activé par défaut — utilisation en réseau local uniquement"),
        ]),
        Spacer(1, 8),
        Paragraph(
            "Si le navigateur ne s'ouvre pas automatiquement, ouvrez-le manuellement "
            "et saisissez l'URL suivante dans la barre d'adresse :", body),
        Paragraph("http://127.0.0.1:8000", code_sty),
        alert("ℹ️", "Pour un accès depuis d'autres postes du réseau, remplacez 127.0.0.1 par l'adresse IP "
              "du poste hébergeant HelpDesk IT et assurez-vous que le pare-feu autorise le port 8000.", LBLUE, BLUE),
        PageBreak(),
    ]

    # ══ Chapitre 6 — Connexion et configuration initiale ═════════════════════
    elems += [
        Paragraph("6.  Connexion et configuration initiale", h1), hr(),
        Spacer(1, 4),
        section_hdr("6.1  Comptes par défaut"),
        Spacer(1, 6),
        Paragraph(
            "Au premier lancement, la base de données est vide. Exécutez le script de données de test "
            "pour créer les comptes initiaux (facultatif, démo uniquement) :", body),
        Paragraph("python seed.py", code_sty),
        Paragraph("Les comptes créés par seed.py sont :", body),
        info_table([
            ("admin  / admin123",   "Administrateur — accès complet"),
            ("jdupont / tech123",   "Technicien — gestion des tickets"),
            ("mmartin / user123",   "Utilisateur standard — création de tickets"),
        ]),
        Spacer(1, 8),
        alert("🔴", "IMPORTANT : Changez impérativement le mot de passe administrateur avant toute mise en production.", LRED, RED),
        Spacer(1, 10),
        section_hdr("6.2  Créer le premier compte administrateur manuellement"),
        Spacer(1, 6),
        Paragraph(
            "Pour créer un compte sans passer par seed.py, utilisez l'API directement :", body),
        Paragraph(
            'Ouvrez PowerShell et exécutez :', body),
        Paragraph(
            'Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/api/auth/register" '
            '-ContentType "application/json" '
            '-Body \'{"username":"admin","email":"admin@entreprise.fr","password":"MotDePasse!123"}\'',
            code_sty),
        Paragraph(
            "Ensuite, depuis la base SQLite (outil DB Browser for SQLite), "
            "modifiez la valeur du champ <b>role</b> à <b>admin</b> pour ce compte.", body),
        alert("ℹ️", "La gestion des rôles est disponible directement dans l'interface pour les administrateurs "
              "(menu Administration → Utilisateurs).", LBLUE, BLUE),
        PageBreak(),
    ]

    # ══ Chapitre 7 — Lancement automatique ═══════════════════════════════════
    elems += [
        Paragraph("7.  Lancement en arrière-plan / au démarrage Windows", h1), hr(),
        Paragraph(
            "Pour que HelpDesk IT démarre automatiquement avec Windows, "
            "vous pouvez créer une tâche planifiée :", body),
        Paragraph("<b>Via l'interface graphique (Planificateur de tâches Windows) :</b>", h3),
        Paragraph("1. Ouvrez le Planificateur de tâches (taskschd.msc)", bullet),
        Paragraph('2. Cliquez sur "Créer une tâche de base…"', bullet),
        Paragraph('3. Nom : <b>HelpDesk IT</b>', bullet),
        Paragraph('4. Déclencheur : <b>Au démarrage de l\'ordinateur</b>', bullet),
        Paragraph('5. Action : <b>Démarrer un programme</b>', bullet),
        Paragraph(r'6. Programme : <b>C:\Program Files\HelpDesk IT\HelpDesk IT.exe</b>', bullet),
        Paragraph('7. Cochez "Exécuter avec les autorisations maximales"', bullet),
        Paragraph('8. Validez et testez en redémarrant le poste', bullet),
        Spacer(1, 8),
        Paragraph("<b>Via PowerShell (en tant qu'Administrateur) :</b>", h3),
        Paragraph(
            r'$action = New-ScheduledTaskAction -Execute "C:\Program Files\HelpDesk IT\HelpDesk IT.exe"' + '\n' +
            r'$trigger = New-ScheduledTaskTrigger -AtStartup' + '\n' +
            r'Register-ScheduledTask -TaskName "HelpDesk IT" -Action $action -Trigger $trigger -RunLevel Highest',
            code_sty),
        alert("ℹ️", "Le service écoute uniquement sur 127.0.0.1 par défaut. "
              "Il ne sera pas accessible depuis le réseau sans modification de la configuration.", LBLUE, BLUE),
        PageBreak(),
    ]

    # ══ Chapitre 8 — Résolution des problèmes ════════════════════════════════
    elems += [
        Paragraph("8.  Résolution des problèmes courants", h1), hr(),
        Spacer(1, 6),
    ]
    issues = [
        ("Le navigateur ne s'ouvre pas automatiquement",
         "Ouvrez manuellement votre navigateur et accédez à http://127.0.0.1:8000. "
         "Vérifiez qu'aucun logiciel de sécurité ne bloque l'ouverture automatique.",
         LBLUE, BLUE),
        ("Erreur « Port 8000 déjà utilisé »",
         "Un autre service utilise le port 8000. Identifiez-le avec la commande PowerShell : "
         "netstat -ano | findstr :8000\n"
         "Arrêtez le processus concerné ou modifiez le port dans launcher.py.",
         LORAN, ORANGE),
        ("Page blanche ou erreur 502 au chargement",
         "Le serveur n'a pas encore démarré. Patientez 10 secondes puis rafraîchissez la page (F5). "
         "Si le problème persiste, relancez l'application.",
         LORAN, ORANGE),
        ("Erreur « Impossible de trouver la base de données »",
         "Vérifiez que le dossier %APPDATA%\\HelpDesk IT\\ existe et est accessible en écriture. "
         "Ce problème peut survenir si le profil utilisateur est redirigé vers un partage réseau lent.",
         LORAN, ORANGE),
        ("L'installation MSI échoue avec le code 1603",
         "Erreur d'installation générique Windows. Assurez-vous d'exécuter le MSI en tant "
         "qu'Administrateur (clic droit → Exécuter en tant qu'administrateur). "
         "Consultez les journaux dans %TEMP%\\MSI*.log.",
         LRED, RED),
        ("Antivirus bloque l'exécution",
         "L'exécutable PyInstaller peut déclencher une fausse alerte. Ajoutez une exclusion "
         r"dans votre antivirus pour C:\Program Files\HelpDesk IT\.",
         LORAN, ORANGE),
    ]
    for (prob, sol, bg, bd) in issues:
        elems += [
            Paragraph(f"<b>Problème :</b> {prob}", h3),
            alert("→", f"Solution : {sol}", bg, bd),
            Spacer(1, 6),
        ]

    elems.append(PageBreak())

    # ══ Chapitre 9 — Désinstallation ═════════════════════════════════════════
    elems += [
        Paragraph("9.  Désinstallation", h1), hr(),
        Paragraph("<b>Méthode 1 — Via le Panneau de configuration :</b>", h3),
        Paragraph("1. Ouvrez <b>Panneau de configuration → Programmes → Programmes et fonctionnalités</b>", bullet),
        Paragraph("2. Sélectionnez <b>HelpDesk IT</b> dans la liste", bullet),
        Paragraph("3. Cliquez sur <b>Désinstaller</b> et confirmez", bullet),
        Spacer(1, 6),
        Paragraph("<b>Méthode 2 — Via les Paramètres Windows 11 :</b>", h3),
        Paragraph("1. <b>Démarrer → Paramètres → Applications → Applications installées</b>", bullet),
        Paragraph("2. Recherchez <b>HelpDesk IT</b>", bullet),
        Paragraph("3. Cliquez sur les trois points ⋮ → <b>Désinstaller</b>", bullet),
        Spacer(1, 6),
        Paragraph("<b>Méthode 3 — Via PowerShell (silencieux) :</b>", h3),
        Paragraph('$app = Get-WmiObject Win32_Product | Where-Object { $_.Name -eq "HelpDesk IT" }\n$app.Uninstall()', code_sty),
        Spacer(1, 8),
        alert("ℹ️", "La désinstallation supprime les fichiers du programme mais conserve "
              "les données dans %APPDATA%\\HelpDesk IT\\ (base de données et configuration). "
              "Supprimez ce dossier manuellement pour effacer toutes les données.", LBLUE, BLUE),
        alert("⚠️", "Fermez HelpDesk IT avant de désinstaller pour éviter les fichiers verrouillés.", LORAN, ORANGE),
        Spacer(1, 20),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e0e0e0"), spaceAfter=8),
        Paragraph(
            f"HelpDesk IT v1.0  •  Procédure d'installation  •  "
            f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}  •  {current_user.username}",
            sty("ft", fontSize=8, fontName="Helvetica", textColor=GREY, alignment=TA_CENTER)
        ),
    ]

    doc.build(elems)
    buf.seek(0)
    filename = f"helpdesk_installation_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/export/pdf")
def export_tickets_pdf(
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    type_group: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    assigned_to_id: Optional[int] = Query(None),
    unassigned: bool = Query(False),
    mine: bool = Query(False),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    q = db.query(models.Ticket)
    if mine:
        q = q.filter(models.Ticket.created_by_id == current_user.id)
    if status:
        q = q.filter(models.Ticket.status == status)
    if type:
        q = q.filter(models.Ticket.type == type)
    if type_group == "incident":
        q = q.filter(models.Ticket.type.in_(INCIDENT_TYPES))
    elif type_group == "demande":
        q = q.filter(models.Ticket.type.in_(DEMANDE_TYPES))
    if priority:
        q = q.filter(models.Ticket.priority == priority)
    if category:
        q = q.filter(models.Ticket.category == category)
    if unassigned:
        q = q.filter(models.Ticket.assigned_to_id == None)
    elif assigned_to_id is not None:
        q = q.filter(models.Ticket.assigned_to_id == assigned_to_id)
    if search:
        q = q.filter(models.Ticket.title.ilike(f"%{search}%"))
    tickets = q.order_by(models.Ticket.created_at.desc()).all()

    STATUS_COLORS = {
        "ouvert": colors.HexColor("#1976d2"),
        "en_cours": colors.HexColor("#f57c00"),
        "resolu": colors.HexColor("#388e3c"),
        "ferme": colors.HexColor("#757575"),
    }
    PRIORITY_COLORS = {
        "faible": colors.HexColor("#9e9e9e"),
        "normale": colors.HexColor("#1976d2"),
        "haute": colors.HexColor("#f57c00"),
        "critique": colors.HexColor("#c62828"),
    }
    STATUS_LABELS   = {"ouvert": "Ouvert", "en_cours": "En cours", "resolu": "Résolu", "ferme": "Fermé"}
    PRIORITY_LABELS = {"faible": "Faible", "normale": "Normale", "haute": "Haute", "critique": "Critique"}
    TYPE_LABELS = {
        "incident": "Incident", "panne": "Panne", "dysfonctionnement": "Dysfonct.",
        "alerte_securite": "Alerte sécu.", "coupure_reseau": "Coupure réseau",
        "intrusion": "Intrusion", "perte_donnees": "Perte données",
        "surcharge_systeme": "Surcharge syst.", "panne_electrique": "Panne électrique",
        "demande": "Demande", "demande_acces": "D. accès",
        "demande_installation": "D. install.", "demande_materiel": "D. matériel",
        "demande_information": "D. info", "demande_formation": "D. formation",
        "demande_sauvegarde": "D. sauvegarde", "demande_demenagement": "D. déménag.",
        "demande_licence": "D. licence",
        "ransomware": "Ransomware", "fuite_donnees": "Fuite données",
        "defaillance_serveur": "Défaillance srv.", "erreur_reseau": "Erreur réseau",
        "vol_equipement": "Vol équipement", "coupure_telephonie": "Coupure tél.",
        "ecran_bleu": "Écran bleu", "peripherique_defaillant": "Périphérique déf.",
        "spam_massif": "Spam massif", "probleme_impression": "Pb. impression",
        "demande_deblockage_compte": "D. déblocage", "demande_vpn": "D. VPN",
        "demande_messagerie": "D. messagerie", "demande_impression_config": "D. impression",
        "demande_badge_acces": "D. badge", "demande_onboarding": "D. onboarding",
        "demande_offboarding": "D. offboarding", "demande_audit_securite": "D. audit sécu.",
        "demande_intervention_site": "D. intervention", "demande_certificat_ssl": "D. certificat",
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", fontSize=16, fontName="Helvetica-Bold",
                                 spaceAfter=4, textColor=colors.HexColor("#1565c0"))
    sub_style   = ParagraphStyle("sub", fontSize=9, fontName="Helvetica",
                                 spaceAfter=12, textColor=colors.HexColor("#757575"))
    cell_style  = ParagraphStyle("cell", fontSize=8, fontName="Helvetica", leading=10)

    elements = [
        Paragraph("HelpDesk IT — Export des tickets", title_style),
        Paragraph(
            f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')} "
            f"par {current_user.username}  •  {len(tickets)} ticket(s)",
            sub_style
        ),
    ]

    headers = ["#", "Titre", "Type", "Catégorie", "Priorité", "Statut", "Créateur", "Assigné à", "Date"]
    col_widths = [1*cm, 7*cm, 3*cm, 2.5*cm, 2*cm, 2*cm, 2.5*cm, 2.5*cm, 3*cm]

    data = [headers]
    row_commands = []

    for i, t in enumerate(tickets, start=1):
        row = i + 1  # +1 for header
        status_col  = STATUS_COLORS.get(t.status, colors.grey)
        priority_col = PRIORITY_COLORS.get(t.priority, colors.grey)

        data.append([
            str(t.id),
            Paragraph(t.title[:80] + ("…" if len(t.title) > 80 else ""), cell_style),
            TYPE_LABELS.get(t.type, t.type),
            t.category.capitalize(),
            PRIORITY_LABELS.get(t.priority, t.priority),
            STATUS_LABELS.get(t.status, t.status),
            t.creator.username,
            t.assignee.username if t.assignee else "—",
            t.created_at.strftime("%d/%m/%Y") if t.created_at else "",
        ])
        row_commands += [
            ("TEXTCOLOR", (4, row), (4, row), priority_col),
            ("TEXTCOLOR", (5, row), (5, row), status_col),
            ("FONTNAME",  (4, row), (5, row), "Helvetica-Bold"),
        ]
        if i % 2 == 0:
            row_commands.append(("BACKGROUND", (0, row), (-1, row), colors.HexColor("#f5f5f5")))

    table_style = TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#1565c0")),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0), 9),
        ("ALIGN",        (0, 0), (-1, -1), "LEFT"),
        ("ALIGN",        (0, 0), (0, -1), "CENTER"),
        ("FONTSIZE",     (0, 1), (-1, -1), 8),
        ("ROWBACKGROUND",(0, 0), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("GRID",         (0, 0), (-1, -1), 0.4, colors.HexColor("#e0e0e0")),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
    ] + row_commands)

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(table_style)
    elements.append(table)

    doc.build(elements)
    buf.seek(0)
    filename = f"tickets_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    all_tickets = db.query(models.Ticket).all()
    incident_types = {"incident","panne","dysfonctionnement","alerte_securite","coupure_reseau"}
    return {
        "total": len(all_tickets),
        "ouvert": sum(1 for t in all_tickets if t.status == "ouvert"),
        "en_cours": sum(1 for t in all_tickets if t.status == "en_cours"),
        "resolu": sum(1 for t in all_tickets if t.status == "resolu"),
        "ferme": sum(1 for t in all_tickets if t.status == "ferme"),
        "incidents": sum(1 for t in all_tickets if t.type in incident_types),
        "demandes": sum(1 for t in all_tickets if t.type not in incident_types),
        "faible": sum(1 for t in all_tickets if t.priority == "faible"),
        "normale": sum(1 for t in all_tickets if t.priority == "normale"),
        "haute": sum(1 for t in all_tickets if t.priority == "haute"),
        "critique": sum(1 for t in all_tickets if t.priority == "critique"),
        "by_category": {
            cat: sum(1 for t in all_tickets if t.category == cat)
            for cat in ("materiel","logiciel","reseau","securite","telephonie","imprimante","autre")
        },
        "by_type": {
            t_type: sum(1 for t in all_tickets if t.type == t_type)
            for t_type in sorted(INCIDENT_TYPES | DEMANDE_TYPES)
        },
    }


@router.get("/sla")
def get_sla(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tickets = db.query(models.Ticket).filter(
        models.Ticket.status.in_(["ouvert", "en_cours"])
    ).order_by(models.Ticket.created_at.asc()).all()

    items = []
    for t in tickets:
        sla = get_sla_status(t)
        items.append({
            "id": t.id,
            "title": t.title,
            "priority": t.priority,
            "status": t.status,
            "type": t.type,
            "category": t.category,
            "creator": t.creator.username,
            "assignee": t.assignee.username if t.assignee else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "sla": sla,
        })

    items.sort(key=lambda x: (
        {"breach": 0, "warning": 1, "ok": 2}.get(x["sla"]["status"], 3),
        x["sla"]["remaining_h"] if x["sla"]["remaining_h"] is not None else 9999,
    ))

    summary = get_sla_summary(tickets)
    return {"items": items, "summary": summary, "delays": SLA_DELAYS}


@router.get("/my-stats")
def get_my_stats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    my = db.query(models.Ticket).filter(models.Ticket.created_by_id == current_user.id).all()
    assigned = db.query(models.Ticket).filter(models.Ticket.assigned_to_id == current_user.id).all()
    return {
        "created":        len(my),
        "ouvert":         sum(1 for t in my if t.status == "ouvert"),
        "en_cours":       sum(1 for t in my if t.status == "en_cours"),
        "resolu":         sum(1 for t in my if t.status == "resolu"),
        "ferme":          sum(1 for t in my if t.status == "ferme"),
        "critique":       sum(1 for t in my if t.priority == "critique"),
        "assigned_to_me": len(assigned),
        "assigned_open":  sum(1 for t in assigned if t.status in ("ouvert", "en_cours")),
        "assigned_critique": sum(1 for t in assigned if t.priority == "critique" and t.status in ("ouvert","en_cours")),
    }


@router.get("/reports")
def get_reports(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    all_tickets = db.query(models.Ticket).all()
    resolved = [t for t in all_tickets if t.status in ("resolu", "ferme")]

    # Temps moyen de résolution par priorité (en heures)
    # Utilise updated_at si disponible, sinon now() comme approximation
    avg_resolution = {}
    for priority in ("critique", "haute", "normale", "faible"):
        pts = [t for t in resolved if t.priority == priority and t.created_at]
        if pts:
            total_h = 0
            for t in pts:
                end = t.updated_at or datetime.utcnow()
                total_h += (end - t.created_at).total_seconds() / 3600
            avg_resolution[priority] = round(total_h / len(pts), 1)
        else:
            avg_resolution[priority] = None

    # Top assignés : total assigné + nb résolus
    assignee_stats = {}
    for t in all_tickets:
        if t.assignee:
            name = t.assignee.username
            if name not in assignee_stats:
                assignee_stats[name] = {"total": 0, "resolved": 0}
            assignee_stats[name]["total"] += 1
            if t.status in ("resolu", "ferme"):
                assignee_stats[name]["resolved"] += 1

    top_assignees = sorted(
        [{"name": k, **v} for k, v in assignee_stats.items()],
        key=lambda x: x["resolved"],
        reverse=True,
    )[:8]

    total = len(all_tickets)
    resolution_rate = round(len(resolved) / total * 100, 1) if total else 0

    return {
        "resolution_rate": resolution_rate,
        "avg_resolution_h": avg_resolution,
        "top_assignees": top_assignees,
        "total": total,
        "resolved_count": len(resolved),
    }


@router.get("/{ticket_id}", response_model=schemas.TicketDetailOut)
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    ticket = db.query(models.Ticket).filter(models.Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    return ticket


@router.patch("/{ticket_id}", response_model=schemas.TicketDetailOut)
def update_ticket(
    ticket_id: int,
    ticket_in: schemas.TicketUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    ticket = db.query(models.Ticket).filter(models.Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable")

    is_tech_or_admin = current_user.role in ("technician", "admin")
    is_owner = ticket.created_by_id == current_user.id

    if not is_tech_or_admin and not is_owner:
        raise HTTPException(status_code=403, detail="Accès refusé")

    # Only tech/admin can change status, priority, assignment
    if ticket_in.status is not None:
        if not is_tech_or_admin:
            raise HTTPException(status_code=403, detail="Seuls les techniciens peuvent changer le statut")
        if ticket_in.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="Statut invalide")
        if ticket.status != ticket_in.status:
            _record_history(db, ticket.id, current_user.id, "statut", ticket.status, ticket_in.status)
            ticket.status = ticket_in.status

    if ticket_in.priority is not None:
        if not is_tech_or_admin:
            raise HTTPException(status_code=403, detail="Seuls les techniciens peuvent changer la priorité")
        if ticket_in.priority not in VALID_PRIORITIES:
            raise HTTPException(status_code=400, detail="Priorité invalide")
        if ticket.priority != ticket_in.priority:
            _record_history(db, ticket.id, current_user.id, "priorité", ticket.priority, ticket_in.priority)
            ticket.priority = ticket_in.priority

    if ticket_in.assigned_to_id is not None:
        if not is_tech_or_admin:
            raise HTTPException(status_code=403, detail="Seuls les techniciens peuvent assigner un ticket")
        assignee = db.query(models.User).filter(models.User.id == ticket_in.assigned_to_id).first()
        if not assignee:
            raise HTTPException(status_code=404, detail="Technicien introuvable")
        old_name = ticket.assignee.username if ticket.assignee else "Non assigné"
        _record_history(db, ticket.id, current_user.id, "assigné à", old_name, assignee.username)
        ticket.assigned_to_id = ticket_in.assigned_to_id

    if ticket_in.title is not None:
        ticket.title = ticket_in.title
    if ticket_in.description is not None:
        ticket.description = ticket_in.description
    if ticket_in.category is not None:
        if ticket_in.category not in VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail="Catégorie invalide")
        ticket.category = ticket_in.category

    db.commit()
    db.refresh(ticket)
    broadcaster.broadcast_sync({
        "type": "ticket_updated",
        "message": f"Ticket #{ticket.id} mis à jour : {ticket.title}",
        "ticket_id": ticket.id,
        "by": current_user.username,
    })
    return ticket


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    ticket = db.query(models.Ticket).filter(models.Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    db.delete(ticket)
    db.commit()


@router.post("/{ticket_id}/comments", response_model=schemas.CommentOut, status_code=201)
def add_comment(
    ticket_id: int,
    comment_in: schemas.CommentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    ticket = db.query(models.Ticket).filter(models.Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket introuvable")
    if not comment_in.content.strip():
        raise HTTPException(status_code=400, detail="Le commentaire ne peut pas être vide")

    comment = models.Comment(
        ticket_id=ticket_id,
        user_id=current_user.id,
        content=comment_in.content.strip(),
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    broadcaster.broadcast_sync({
        "type": "comment_added",
        "message": f"Nouveau commentaire sur le ticket #{ticket_id} par {current_user.username}",
        "ticket_id": ticket_id,
        "by": current_user.username,
    })
    return comment
