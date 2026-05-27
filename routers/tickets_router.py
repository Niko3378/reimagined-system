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
INCIDENT_TYPES = {"incident","panne","dysfonctionnement","alerte_securite","coupure_reseau","intrusion","perte_donnees","surcharge_systeme","panne_electrique","virus","phishing","crash_application","corruption_donnees","indisponibilite_service","acces_refuse","ransomware","erreur_reseau","ecran_bleu","peripherique_defaillant","probleme_impression"}
DEMANDE_TYPES  = {"demande","demande_acces","demande_installation","demande_materiel","demande_information","demande_formation","demande_sauvegarde","demande_demenagement","demande_licence","demande_reinitialisation_mdp","demande_creation_compte","demande_assistance","demande_configuration","demande_mise_a_jour","demande_archivage","demande_deblockage_compte","demande_vpn","demande_messagerie","demande_impression_config","demande_badge_acces"}
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
        ("erreur_reseau",          "Erreur réseau / DNS",     "haute",      8),
        ("ecran_bleu",             "Écran bleu (BSOD)",       "normale",   24),
        ("peripherique_defaillant","Périphérique défaillant", "normale",   24),
        ("probleme_impression",    "Problème d'impression",   "faible",    72),
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
        "ransomware": "Ransomware", "erreur_reseau": "Erreur réseau",
        "ecran_bleu": "Écran bleu", "peripherique_defaillant": "Périphérique déf.",
        "probleme_impression": "Pb. impression",
        "demande_deblockage_compte": "D. déblocage", "demande_vpn": "D. VPN",
        "demande_messagerie": "D. messagerie", "demande_impression_config": "D. impression",
        "demande_badge_acces": "D. badge",
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
