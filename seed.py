"""
Script de peuplement de la base de données avec des données de test.
Usage :
    python seed.py          # Peuple si la base est vide
    python seed.py --force  # Vide et repeuple même si des données existent
"""
import sys
from datetime import datetime, timedelta, timezone
from database import SessionLocal, engine
import models
from auth import hash_password

models.Base.metadata.create_all(bind=engine)


def seed(force=False):
    db = SessionLocal()

    if db.query(models.User).count() > 0:
        if not force:
            print("Base déjà peuplée. Utilisez --force pour réinitialiser.")
            db.close()
            return
        print("Réinitialisation de la base...")
        db.query(models.TicketHistory).delete()
        db.query(models.Comment).delete()
        db.query(models.Ticket).delete()
        db.query(models.TicketTemplate).delete()
        db.query(models.TicketProcessTask).delete()
        db.query(models.TicketProcess).delete()
        db.query(models.ProcessTemplateStep).delete()
        db.query(models.ProcessTemplate).delete()
        db.query(models.User).delete()
        db.commit()

    # ── Utilisateurs ──────────────────────────────────────────────────────────
    print("Création des utilisateurs...")
    admin    = models.User(username="admin",    email="admin@helpdesk.fr",
                           hashed_password=hash_password("admin123"), role="admin")
    jdupont  = models.User(username="jdupont",  email="jean.dupont@helpdesk.fr",
                           hashed_password=hash_password("tech123"),  role="technician")
    mmartin  = models.User(username="mmartin",  email="marie.martin@helpdesk.fr",
                           hashed_password=hash_password("user123"),  role="user")
    db.add_all([admin, jdupont, mmartin])
    db.commit()

    # ── Helpers ───────────────────────────────────────────────────────────────
    def ticket(title, description, type, category, priority, status,
               creator, assignee=None, created_days_ago=0):
        t = models.Ticket(
            title=title, description=description,
            type=type, category=category, priority=priority, status=status,
            created_by_id=creator.id,
            assigned_to_id=assignee.id if assignee else None,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=created_days_ago),
        )
        db.add(t)
        db.flush()
        return t

    def history(t, user, field, old_val, new_val, days_ago=0):
        db.add(models.TicketHistory(
            ticket_id=t.id, user_id=user.id,
            field_changed=field, old_value=old_val, new_value=new_val,
            changed_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago),
        ))

    def comment(t, user, content, days_ago=0):
        db.add(models.Comment(
            ticket_id=t.id, user_id=user.id, content=content,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago),
        ))

    # ── Tickets ───────────────────────────────────────────────────────────────
    print("Création des tickets...")

    # ── Incidents classiques ──
    t1 = ticket("Écran bleu au démarrage",
        "Mon PC affiche un écran bleu (BSOD) avec le code KERNEL_SECURITY_CHECK_FAILURE "
        "depuis ce matin. Le problème survient dès le lancement de Windows.",
        "incident", "logiciel", "haute", "ouvert", mmartin, created_days_ago=5)
    history(t1, mmartin, "création", None, "ouvert", days_ago=5)

    t2 = ticket("VPN ne fonctionne plus depuis la mise à jour",
        "Après la mise à jour Windows du 25/05, le client VPN Cisco AnyConnect refuse "
        "de se connecter. Erreur : unable to establish VPN. Affecte toute l'équipe commerciale.",
        "incident", "reseau", "critique", "en_cours", mmartin, jdupont, created_days_ago=8)
    history(t2, mmartin,  "création",  None,       "ouvert",   days_ago=8)
    history(t2, jdupont,  "statut",    "ouvert",   "en_cours", days_ago=7)
    history(t2, admin,    "assigné à", "Non assigné", "jdupont", days_ago=7)
    comment(t2, jdupont,
        "Problème identifié : conflit entre KB5034441 et le pilote réseau. "
        "Solution en cours de test sur un poste pilote.", days_ago=6)

    t3 = ticket("Installation Adobe Acrobat Pro",
        "Besoin d'Adobe Acrobat Pro pour créer et éditer des PDF dans le cadre "
        "du projet contrats clients. Merci de procéder à l'installation sur mon poste.",
        "demande", "logiciel", "normale", "resolu", mmartin, jdupont, created_days_ago=10)
    history(t3, mmartin, "création", None,       "ouvert",   days_ago=10)
    history(t3, jdupont, "statut",   "ouvert",   "en_cours", days_ago=9)
    history(t3, jdupont, "statut",   "en_cours", "resolu",   days_ago=8)

    t4 = ticket("Souris sans fil déconnectée en permanence",
        "La souris Logitech MX Master se déconnecte toutes les 5 minutes. "
        "Remplacement de la pile effectué sans amélioration. Problème présent depuis 1 semaine.",
        "incident", "materiel", "faible", "ouvert", mmartin, created_days_ago=3)
    history(t4, mmartin, "création", None, "ouvert", days_ago=3)

    t5 = ticket("Accès refusé au dossier partagé RH",
        "Impossible d'accéder au dossier \\\\serveur\\RH depuis hier matin. "
        "Message : accès refusé. J'avais les droits la semaine dernière. "
        "Besoin urgent pour préparer les fiches de paie.",
        "incident", "reseau", "haute", "en_cours", mmartin, jdupont, created_days_ago=4)
    history(t5, mmartin, "création",  None,       "ouvert",   days_ago=4)
    history(t5, jdupont, "statut",    "ouvert",   "en_cours", days_ago=3)
    history(t5, admin,   "assigné à", "Non assigné", "jdupont", days_ago=3)

    t6 = ticket("Demande second écran pour télétravail",
        "Dans le cadre de mon passage en télétravail 3 jours par semaine, je sollicite "
        "la mise à disposition d'un second écran 24 pouces.",
        "demande_materiel", "materiel", "faible", "ferme", mmartin, jdupont, created_days_ago=15)
    history(t6, mmartin, "création", None,       "ouvert",   days_ago=15)
    history(t6, jdupont, "statut",   "ouvert",   "resolu",   days_ago=12)
    history(t6, jdupont, "statut",   "resolu",   "ferme",    days_ago=10)

    t7 = ticket("Antivirus signale un fichier suspect",
        "Windows Defender a mis en quarantaine Invoice_2026.exe reçu par email. "
        "Alerte : Trojan:Win32/Wacatac. Le fichier a été ouvert par erreur avant la détection.",
        "alerte_securite", "securite", "critique", "en_cours", mmartin, jdupont, created_days_ago=2)
    history(t7, mmartin, "création",  None,       "ouvert",   days_ago=2)
    history(t7, admin,   "statut",    "ouvert",   "en_cours", days_ago=1)
    history(t7, admin,   "assigné à", "Non assigné", "jdupont", days_ago=1)
    comment(t7, admin,
        "Fichier analysé : domaine frauduleux détecté. Mot de passe utilisateur réinitialisé "
        "par précaution. Signalement CERT en cours.", days_ago=1)

    # ── Nouvelles pannes ──
    t8 = ticket("Serveur de fichiers inaccessible depuis 8h",
        "Le serveur NAS principal (\\\\SRV-NAS01) est totalement hors service depuis 8h. "
        "Aucun utilisateur ne peut accéder à ses fichiers. Impact sur toute la société.",
        "panne", "reseau", "critique", "en_cours", mmartin, admin, created_days_ago=1)
    history(t8, mmartin, "création",  None,       "ouvert",   days_ago=1)
    history(t8, admin,   "statut",    "ouvert",   "en_cours", days_ago=1)
    comment(t8, admin,
        "Intervention en cours sur le NAS. Problème identifié : disque RAID dégradé. "
        "Reconstruction en cours, estimé 2h.", days_ago=0)

    t9 = ticket("Messagerie Outlook très lente à charger",
        "Depuis la mise à jour Outlook du 24/05, les emails mettent 2 à 3 minutes à s'afficher. "
        "Problème touche une dizaine de postes au service comptabilité.",
        "dysfonctionnement", "logiciel", "haute", "en_cours", mmartin, jdupont, created_days_ago=6)
    history(t9, mmartin, "création",  None,       "ouvert",   days_ago=6)
    history(t9, jdupont, "statut",    "ouvert",   "en_cours", days_ago=5)

    t10 = ticket("Perte de connexion internet bâtiment B",
        "Le bâtiment B est totalement coupé d'internet depuis 14h. "
        "WiFi et filaire affectés. Le bâtiment A fonctionne normalement.",
        "coupure_reseau", "reseau", "haute", "ouvert", mmartin, created_days_ago=0)
    history(t10, mmartin, "création", None, "ouvert", days_ago=0)

    t11 = ticket("Création compte stagiaire - Marie Lefebvre",
        "Merci de créer un compte Active Directory pour notre stagiaire Marie Lefebvre "
        "(marie.lefebvre@entreprise.fr). Accès : messagerie, SharePoint RH, logiciel de paie. "
        "Arrivée le 01/06.",
        "demande_acces", "logiciel", "normale", "resolu", mmartin, jdupont, created_days_ago=12)
    history(t11, mmartin, "création", None,       "ouvert",   days_ago=12)
    history(t11, jdupont, "statut",   "ouvert",   "resolu",   days_ago=10)

    t12 = ticket("Installation AutoCAD 2025 poste bureau études",
        "Le bureau des études a besoin d'AutoCAD 2025 sur le poste de M. Girard (PC-ETUDES-04). "
        "La licence est disponible dans le gestionnaire de licences.",
        "demande_installation", "logiciel", "normale", "resolu", admin, jdupont, created_days_ago=9)
    history(t12, admin,   "création", None,       "ouvert",   days_ago=9)
    history(t12, jdupont, "statut",   "ouvert",   "resolu",   days_ago=7)

    t13 = ticket("Remplacement clavier défectueux",
        "Le clavier du poste de Mme Durand (comptabilité, bureau 214) a plusieurs touches "
        "défaillantes (E, R, T). Merci de procéder au remplacement.",
        "demande_materiel", "materiel", "faible", "ouvert", mmartin, created_days_ago=2)
    history(t13, mmartin, "création", None, "ouvert", days_ago=2)

    t14 = ticket("Procédure sauvegarde données OneDrive",
        "Pouvez-vous m'expliquer comment configurer la synchronisation automatique "
        "du bureau et des documents vers OneDrive ?",
        "demande_information", "logiciel", "faible", "ouvert", mmartin, created_days_ago=1)
    history(t14, mmartin, "création", None, "ouvert", days_ago=1)

    # ── Nouveaux types ──
    t15 = ticket("Tentative intrusion SSH serveur production",
        "Le firewall a bloqué 3 200 tentatives de connexion SSH en 2h sur SRV-PROD-01 "
        "depuis une IP étrangère (185.234.x.x). Attaque bruteforce en cours.",
        "intrusion", "securite", "critique", "en_cours", admin, admin, created_days_ago=0)
    history(t15, admin, "création",  None,       "ouvert",   days_ago=0)
    history(t15, admin, "statut",    "ouvert",   "en_cours", days_ago=0)
    comment(t15, admin,
        "IP source bannie au niveau firewall. Analyse des logs en cours. "
        "Fail2Ban activé sur tous les serveurs exposés.")

    t16 = ticket("Base de données clients corrompue après crash",
        "Suite à une coupure de courant, la base MySQL CRM est partiellement corrompue. "
        "3 tables inaccessibles. Dernière sauvegarde disponible : J-1. "
        "Environ 300 enregistrements potentiellement perdus.",
        "perte_donnees", "logiciel", "critique", "en_cours", mmartin, admin, created_days_ago=1)
    history(t16, mmartin, "création",  None,       "ouvert",   days_ago=1)
    history(t16, admin,   "statut",    "ouvert",   "en_cours", days_ago=1)
    comment(t16, admin,
        "Restauration de la sauvegarde J-1 en cours. Perte estimée à 47 enregistrements. "
        "Les équipes métier ont été informées.")

    t17 = ticket("Serveur web à 98% CPU depuis 6h",
        "Le serveur NGINX (SRV-WEB-02) est à 98% CPU depuis 6h. "
        "Temps de réponse : 8-12 secondes. Cause probable : script de crawling non contrôlé.",
        "surcharge_systeme", "reseau", "haute", "en_cours", admin, jdupont, created_days_ago=0)
    history(t17, admin,   "création",  None,       "ouvert",   days_ago=0)
    history(t17, jdupont, "statut",    "ouvert",   "en_cours", days_ago=0)
    comment(t17, jdupont,
        "Script incriminé identifié (crawler.py mal configuré). Script arrêté, "
        "CPU redescendu à 12%. Surveillance maintenue 24h.")

    t18 = ticket("Onduleur salle serveur en alarme",
        "L'onduleur APC Smart-UPS 3000 émet une alarme sonore continue. "
        "Les serveurs fonctionnent sur batterie depuis 45 minutes. Autonomie : 20 min restantes.",
        "panne_electrique", "materiel", "critique", "resolu", admin, admin, created_days_ago=3)
    history(t18, admin, "création", None,       "ouvert",   days_ago=3)
    history(t18, admin, "statut",   "ouvert",   "en_cours", days_ago=3)
    history(t18, admin, "statut",   "en_cours", "resolu",   days_ago=2)
    comment(t18, admin,
        "Technicien intervenu en urgence. Module batterie remplacé. "
        "Onduleur opérationnel. Autonomie testée : 45 min. Prévoir remplacement complet sous 6 mois.",
        days_ago=2)

    t19 = ticket("Formation Microsoft 365 pour équipe RH",
        "L'équipe RH (8 personnes) souhaite une formation Teams, SharePoint et OneDrive. "
        "Durée souhaitée : demi-journée. À planifier avant fin juin 2026.",
        "demande_formation", "logiciel", "normale", "ouvert", mmartin, created_days_ago=4)
    history(t19, mmartin, "création", None, "ouvert", days_ago=4)

    t20 = ticket("Mise en place sauvegarde automatique poste direction",
        "M. Martin (Direction) demande une sauvegarde automatique quotidienne vers le NAS. "
        "Dossiers : Bureau, Documents, Téléchargements. Rétention souhaitée : 30 jours.",
        "demande_sauvegarde", "logiciel", "normale", "ouvert", admin, created_days_ago=2)
    history(t20, admin, "création", None, "ouvert", days_ago=2)

    t21 = ticket("Déménagement poste bureau 304 vers open space B2",
        "Le poste de Mme Chen doit être déplacé du bureau 304 vers l'open space B2. "
        "Prévoir reconfiguration réseau et téléphonie. À effectuer le week-end du 07-08 juin.",
        "demande_demenagement", "reseau", "faible", "ouvert", mmartin, created_days_ago=1)
    history(t21, mmartin, "création", None, "ouvert", days_ago=1)

    t22 = ticket("Renouvellement licences Adobe Creative Cloud x5",
        "Les 5 licences Adobe CC du service Marketing expirent le 15 juin 2026. "
        "Merci de procéder au renouvellement annuel et de contacter les achats pour le bon de commande.",
        "demande_licence", "logiciel", "haute", "en_cours", mmartin, jdupont, created_days_ago=5)
    history(t22, mmartin, "création",  None,       "ouvert",   days_ago=5)
    history(t22, jdupont, "statut",    "ouvert",   "en_cours", days_ago=4)
    history(t22, admin,   "assigné à", "Non assigné", "jdupont", days_ago=4)

    # ── Tickets créés par jdupont (technicien signalant des problèmes) ──
    t23 = ticket("Imprimante réseau HP salle de réunion hors service",
        "L'imprimante HP LaserJet de la salle de réunion principale (RDC) ne répond plus "
        "depuis ce matin. Les jobs s'accumulent dans la file. Redémarrage sans effet.",
        "panne", "imprimante", "normale", "en_cours", jdupont, jdupont, created_days_ago=1)
    history(t23, jdupont, "création",  None,     "ouvert",   days_ago=1)
    history(t23, jdupont, "statut",    "ouvert", "en_cours", days_ago=0)
    comment(t23, jdupont,
        "Pilote réinstallé, file d'impression vidée. Problème persiste. "
        "Carte réseau de l'imprimante probablement défaillante. Commande pièce en cours.")

    t24 = ticket("Demande accès VPN pour télétravail",
        "Suite à ma nouvelle organisation en télétravail 2 jours/semaine, "
        "j'ai besoin d'un accès VPN pour me connecter aux ressources internes depuis chez moi.",
        "demande_acces", "reseau", "normale", "resolu", jdupont, admin, created_days_ago=7)
    history(t24, jdupont, "création",  None,       "ouvert",   days_ago=7)
    history(t24, admin,   "statut",    "ouvert",   "en_cours", days_ago=6)
    history(t24, admin,   "statut",    "en_cours", "resolu",   days_ago=5)
    comment(t24, admin,
        "Compte VPN créé. Identifiants envoyés par email sécurisé. "
        "Guide d'installation joint.", days_ago=5)

    t25 = ticket("Mise à jour Windows bloquée sur 12 postes",
        "Les mises à jour Windows Update sont bloquées sur 12 postes du service comptabilité "
        "depuis 3 semaines. Erreur 0x80070057. Les postes sont vulnérables aux derniers CVE.",
        "dysfonctionnement", "logiciel", "haute", "ouvert", jdupont, created_days_ago=3)
    history(t25, jdupont, "création", None, "ouvert", days_ago=3)

    # ── Tickets créés par admin ──
    t26 = ticket("Téléphone IP bureau direction muet",
        "Le téléphone IP Cisco du bureau de la Direction Générale n'émet plus aucun son "
        "en réception d'appel depuis hier. L'écran s'allume mais pas de sonnerie ni audio.",
        "dysfonctionnement", "telephonie", "haute", "en_cours", admin, jdupont, created_days_ago=2)
    history(t26, admin,   "création",  None,       "ouvert",   days_ago=2)
    history(t26, jdupont, "statut",    "ouvert",   "en_cours", days_ago=1)
    history(t26, admin,   "assigné à", "Non assigné", "jdupont", days_ago=1)

    t27 = ticket("Formation sécurité informatique obligatoire",
        "Conformément à la politique sécurité 2026, tous les collaborateurs doivent suivre "
        "la formation e-learning 'Cybersécurité au quotidien' avant le 30 juin. "
        "Merci de déployer l'accès à la plateforme pour les 45 employés.",
        "demande_formation", "logiciel", "haute", "en_cours", admin, admin, created_days_ago=6)
    history(t27, admin, "création", None,       "ouvert",   days_ago=6)
    history(t27, admin, "statut",   "ouvert",   "en_cours", days_ago=5)
    comment(t27, admin,
        "Plateforme configurée. Invitations envoyées à 45 collaborateurs. "
        "32/45 formations complétées à ce jour.", days_ago=2)

    t28 = ticket("Coupure réseau datacenter lors maintenance",
        "La maintenance programmée du switch core ce soir de 22h à 00h "
        "entraînera une coupure réseau complète du datacenter. "
        "Tous les services hébergés seront indisponibles pendant cette fenêtre.",
        "coupure_reseau", "reseau", "haute", "ferme", admin, admin, created_days_ago=10)
    history(t28, admin, "création", None,       "ouvert",   days_ago=10)
    history(t28, admin, "statut",   "ouvert",   "en_cours", days_ago=10)
    history(t28, admin, "statut",   "en_cours", "resolu",   days_ago=9)
    history(t28, admin, "statut",   "resolu",   "ferme",    days_ago=9)
    comment(t28, admin,
        "Maintenance effectuée sans incident. Retour à la normale à 23h42. "
        "Durée effective : 1h42 sur les 2h prévues.", days_ago=9)

    t29 = ticket("Renouvellement certificat SSL site intranet",
        "Le certificat SSL de l'intranet (intranet.entreprise.fr) expire dans 15 jours. "
        "Merci de procéder au renouvellement avant expiration pour éviter les alertes navigateur.",
        "demande_licence", "reseau", "critique", "ouvert", admin, created_days_ago=0)
    history(t29, admin, "création", None, "ouvert", days_ago=0)

    db.commit()

    # ── Modèles de tickets ────────────────────────────────────────────────────
    print("Création des modèles de tickets...")
    templates_data = [
        ("Réinitialisation mot de passe", "demande_reinitialisation_mdp", "logiciel", "faible",
         "Réinitialisation mot de passe - [Nom Prénom]",
         "Bonjour,\n\nJe souhaite demander la réinitialisation de mon mot de passe.\n\n"
         "Informations :\n- Nom d'utilisateur / email : \n- Application concernée : \n- Raison (compte bloqué, mot de passe oublié) : \n\nMerci d'avance."),
        ("Nouveau poste de travail", "demande_materiel", "materiel", "normale",
         "Demande de nouveau poste de travail - [Nom Prénom]",
         "Bonjour,\n\nJe souhaite faire une demande de nouveau poste de travail.\n\n"
         "Informations :\n- Utilisateur concerné : \n- Date de besoin : \n- Usage prévu (bureautique, développement, CAO...) : \n- Logiciels requis : \n\nMerci."),
        ("Création de compte Active Directory", "demande_creation_compte", "logiciel", "normale",
         "Création de compte AD - [Nom Prénom] - [Service]",
         "Bonjour,\n\nJe demande la création d'un compte Active Directory.\n\n"
         "Informations :\n- Nom : \n- Prénom : \n- Service / département : \n- Responsable hiérarchique : \n- Date d'arrivée : \n- Groupes d'accès requis : \n\nMerci."),
        ("Accès VPN distant", "demande_vpn", "reseau", "normale",
         "Demande d'accès VPN - [Nom Prénom]",
         "Bonjour,\n\nJe souhaite obtenir un accès VPN pour travail à distance.\n\n"
         "Informations :\n- Utilisateur : \n- Justification (télétravail, déplacement...) : \n- Date de début souhaitée : \n- Durée estimée : \n\nMerci."),
        ("Configuration imprimante réseau", "demande_impression_config", "imprimante", "faible",
         "Configuration imprimante réseau - [Poste/Bureau]",
         "Bonjour,\n\nJe rencontre des difficultés pour configurer l'imprimante réseau.\n\n"
         "Informations :\n- Modèle d'imprimante : \n- Adresse IP ou nom réseau : \n- Système d'exploitation du poste : \n- Erreur observée : \n\nMerci."),
        ("Virus / Malware détecté", "virus", "securite", "critique",
         "ALERTE - Virus détecté sur [Nom machine]",
         "URGENT - Virus/Malware détecté.\n\n"
         "Informations :\n- Nom de la machine infectée : \n- Utilisateur connecté : \n- Antivirus utilisé : \n- Message d'alerte affiché : \n- Heure de détection : \n\n"
         "⚠️ La machine a été isolée du réseau en attente d'intervention."),
        ("Logiciel à installer", "demande_installation", "logiciel", "faible",
         "Demande d'installation logiciel - [Nom logiciel] sur [Poste]",
         "Bonjour,\n\nJe souhaite faire installer un logiciel sur mon poste.\n\n"
         "Informations :\n- Logiciel et version : \n- Poste concerné (nom ou IP) : \n- Justification métier : \n- Licence disponible : Oui / Non\n\nMerci."),
        ("Déménagement de poste", "demande_demenagement", "materiel", "faible",
         "Déménagement poste de travail - [Bureau source] → [Bureau destination]",
         "Bonjour,\n\nJe sollicite l'intervention du service informatique pour un déménagement de poste.\n\n"
         "Informations :\n- Utilisateur : \n- Bureau actuel : \n- Nouveau bureau : \n- Date souhaitée : \n- Matériel à déplacer : \n\nMerci."),
    ]
    for (name, ttype, cat, prio, title, desc) in templates_data:
        tpl = models.TicketTemplate(
            name=name, title=title, description=desc,
            type=ttype, category=cat, priority=prio,
            author_id=jdupont.id,
        )
        db.add(tpl)
    db.commit()

    # ── Modèles de processus ──────────────────────────────────────────────────
    print("Création des modèles de processus...")
    process_defs = [
        ("Onboarding nouvel employé", "demande_onboarding",
         "Processus complet d'intégration d'un nouvel employé", [
             (1, "Créer le compte Active Directory", "Créer l'identifiant, définir le mot de passe temporaire et affecter les groupes de sécurité."),
             (2, "Attribuer les licences logicielles", "Office 365, antivirus, outils métier selon le profil."),
             (3, "Configurer le poste de travail", "Installation OS, drivers, logiciels requis et jonction au domaine."),
             (4, "Configurer la messagerie", "Créer la boîte mail, configurer Outlook, ajouter aux listes de diffusion."),
             (5, "Créer les accès applicatifs métier", "ERP, CRM, intranet et autres applications selon le service."),
             (6, "Remettre le matériel et former l'utilisateur", "Remise du poste, téléphone, badges et formation de prise en main."),
         ]),
        ("Offboarding / Départ employé", "demande_offboarding",
         "Processus de clôture des accès lors du départ d'un employé", [
             (1, "Désactiver le compte Active Directory", "Désactiver le compte sans le supprimer pour conserver l'historique."),
             (2, "Révoquer les accès applicatifs", "Supprimer ou désactiver les comptes sur chaque application métier."),
             (3, "Transférer les données et emails", "Rediriger les emails, transférer les fichiers vers le responsable."),
             (4, "Récupérer le matériel informatique", "Collecter PC, téléphone, badge, câbles et accessoires."),
             (5, "Archiver et supprimer le compte", "Archiver les données selon la politique de rétention puis supprimer le compte AD."),
         ]),
        ("Déploiement logiciel", "demande_installation",
         "Processus standard pour le déploiement d'un nouveau logiciel", [
             (1, "Valider les prérequis système", "Vérifier compatibilité OS, espace disque, RAM et dépendances."),
             (2, "Tester en environnement de recette", "Déployer sur poste de test et valider le fonctionnement."),
             (3, "Préparer le package de déploiement", "Créer/adapter le package MSI/SCCM pour déploiement silencieux."),
             (4, "Déployer sur les postes cibles", "Déploiement via SCCM, GPO ou intervention manuelle."),
             (5, "Vérifier et notifier les utilisateurs", "Contrôler le bon fonctionnement et informer les utilisateurs."),
         ]),
        ("Déménagement de poste", "demande_demenagement",
         "Processus de déménagement d'un poste de travail", [
             (1, "Vérifier le câblage du nouveau bureau", "S'assurer que les prises réseau, électrique et téléphonie sont disponibles."),
             (2, "Planifier l'intervention avec l'utilisateur", "Convenir d'un créneau sans impact sur la production."),
             (3, "Démonter et étiqueter le matériel", "Déconnecter et emballer soigneusement chaque équipement."),
             (4, "Réinstaller et reconfigurer le poste", "Rebrancher, vérifier la connexion réseau et les paramètres."),
             (5, "Valider avec l'utilisateur", "Tester l'accès aux ressources réseau et obtenir la validation."),
         ]),
        ("Réponse à incident de sécurité", "intrusion",
         "Processus de réponse en cas d'incident de sécurité", [
             (1, "Isoler le système compromis", "Déconnecter la machine du réseau pour stopper la propagation."),
             (2, "Qualifier et documenter l'incident", "Collecter les logs, identifier la nature et l'étendue de l'attaque."),
             (3, "Notifier les parties prenantes", "Informer la direction, le RSSI et si nécessaire les autorités (CNIL, ANSSI)."),
             (4, "Remédier et nettoyer le système", "Supprimer le malware, corriger les vulnérabilités, réinstaller si nécessaire."),
             (5, "Restaurer et valider", "Restaurer depuis une sauvegarde saine et vérifier l'intégrité."),
             (6, "Rédiger le rapport post-incident", "Documenter le chronologie, les actions et les recommandations."),
         ]),
    ]
    for (name, ttype, desc, steps) in process_defs:
        pt = models.ProcessTemplate(
            name=name, description=desc, ticket_type=ttype, author_id=jdupont.id
        )
        db.add(pt)
        db.flush()
        for (order, sname, sdesc) in steps:
            db.add(models.ProcessTemplateStep(
                template_id=pt.id, order=order, name=sname, description=sdesc
            ))
    db.commit()

    # Résumé
    nb_tickets = db.query(models.Ticket).count()
    nb_users   = db.query(models.User).count()
    nb_comments = db.query(models.Comment).count()
    print(f"[OK] {nb_users} utilisateurs crees  : admin / jdupont / mmartin")
    print(f"[OK] {nb_tickets} tickets crees")
    print(f"[OK] {nb_comments} commentaires ajoutes")
    print()
    print("Comptes de test :")
    print("  admin    / admin123  (Administrateur)")
    print("  jdupont  / tech123   (Technicien)")
    print("  mmartin  / user123   (Utilisateur)")
    db.close()


if __name__ == "__main__":
    force = "--force" in sys.argv
    seed(force=force)
