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
INCIDENT_TYPES = {"incident","panne","dysfonctionnement","alerte_securite","coupure_reseau","intrusion","perte_donnees","surcharge_systeme","panne_electrique","virus","phishing","crash_application","corruption_donnees","indisponibilite_service","acces_refuse"}
DEMANDE_TYPES  = {"demande","demande_acces","demande_installation","demande_materiel","demande_information","demande_formation","demande_sauvegarde","demande_demenagement","demande_licence","demande_reinitialisation_mdp","demande_creation_compte","demande_assistance","demande_configuration","demande_mise_a_jour","demande_archivage"}
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
