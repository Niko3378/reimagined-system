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

    # ── Nouveaux types d'incidents ────────────────────────────────────────────

    t30 = ticket("PC de M. Blanc très lent depuis mise à jour",
        "Depuis la mise à jour Windows du 20/05, le poste PC-BLANC-01 met 8 minutes à démarrer "
        "et les applications mettent 2-3 min à s'ouvrir. Impact fort sur la productivité.",
        "lenteur_systeme", "logiciel", "haute", "ouvert", mmartin, created_days_ago=4)
    history(t30, mmartin, "création", None, "ouvert", days_ago=4)

    t31 = ticket("Mise à jour KB5034441 échoue sur 8 postes comptabilité",
        "La mise à jour cumulative KB5034441 échoue systématiquement avec l'erreur 0x80073701 "
        "sur 8 postes du service comptabilité. Les postes restent en retard de patch.",
        "mise_a_jour_echouee", "logiciel", "normale", "en_cours", jdupont, jdupont, created_days_ago=5)
    history(t31, jdupont, "création", None,       "ouvert",   days_ago=5)
    history(t31, jdupont, "statut",   "ouvert",   "en_cours", days_ago=4)
    comment(t31, jdupont, "Composant CBS corrompu identifié. Exécution de DISM /RestoreHealth en cours sur les postes.", days_ago=3)

    t32 = ticket("Certificat SSL API interne expiré - services bloqués",
        "Le certificat du serveur API interne (api.interne.local) a expiré ce matin. "
        "Les applications métier (ERP, CRM) ne peuvent plus s'authentifier. Impact critique.",
        "certificat_expire", "reseau", "haute", "en_cours", admin, admin, created_days_ago=0)
    history(t32, admin, "création", None,       "ouvert",   days_ago=0)
    history(t32, admin, "statut",   "ouvert",   "en_cours", days_ago=0)
    comment(t32, admin, "Nouveau certificat Let's Encrypt généré et déployé. Tests de validation en cours.")

    t33 = ticket("Sauvegarde nocturne Veeam en échec depuis 3 jours",
        "Les jobs de sauvegarde Veeam B&R échouent chaque nuit depuis le 23/05 avec l'erreur "
        "'Unable to connect to guest'. Les VMs critiques ne sont plus sauvegardées.",
        "sauvegarde_echouee", "logiciel", "haute", "ouvert", admin, created_days_ago=3)
    history(t33, admin, "création", None, "ouvert", days_ago=3)

    t34 = ticket("Attaque DDoS sur le site vitrine - débit saturé",
        "Notre site vitrine (www.entreprise.fr) est victime d'une attaque DDoS depuis 10h. "
        "Bande passante saturée à 100%, site inaccessible. Prestataire hébergeur contacté.",
        "attaque_ddos", "reseau", "critique", "en_cours", admin, admin, created_days_ago=0)
    history(t34, admin, "création", None,       "ouvert",   days_ago=0)
    history(t34, admin, "statut",   "ouvert",   "en_cours", days_ago=0)
    comment(t34, admin, "Mitigation CloudFlare activée. Trafic en cours de filtrage. Site partiellement accessible.")

    t35 = ticket("Compte de Mme Torres piraté - connexion depuis l'étranger",
        "L'Azure AD Conditional Access a détecté une connexion depuis Moscou avec le compte "
        "de Mme Torres (RH). Le compte a été bloqué automatiquement. Vérification et remédiation requises.",
        "acces_non_autorise", "securite", "critique", "en_cours", admin, admin, created_days_ago=1)
    history(t35, admin, "création", None,       "ouvert",   days_ago=1)
    history(t35, admin, "statut",   "ouvert",   "en_cours", days_ago=1)
    comment(t35, admin, "MDP réinitialisé, sessions révoquées, MFA forcé. Analyse de l'activité suspecte en cours.", days_ago=0)

    t36 = ticket("WiFi coupé dans l'open space RDC - 15 postes impactés",
        "Le point d'accès WiFi de l'open space RDC (AP-RDC-03) est hors service depuis 9h. "
        "15 collaborateurs sans connexion. Le câble réseau de remplacement fonctionne.",
        "perte_connexion_wifi", "reseau", "normale", "ouvert", mmartin, created_days_ago=0)
    history(t36, mmartin, "création", None, "ouvert", days_ago=0)

    t37 = ticket("Serveur Exchange indisponible - messagerie hors service",
        "Le serveur Exchange On-Premise (SRV-MAIL-01) est tombé à 14h32. "
        "Tous les utilisateurs ne peuvent plus envoyer ni recevoir d'emails depuis 2h. "
        "Service critique pour le bon fonctionnement de l'entreprise.",
        "messagerie_indisponible", "reseau", "haute", "en_cours", jdupont, jdupont, created_days_ago=0)
    history(t37, jdupont, "création", None,       "ouvert",   days_ago=0)
    history(t37, jdupont, "statut",   "ouvert",   "en_cours", days_ago=0)
    comment(t37, jdupont, "Service de transport Exchange redémarré. Vérification de la file de messages en cours.")

    t38 = ticket("Dossier \\\\SRV-FIC\\COMPTA inaccessible depuis ce matin",
        "Le dossier partagé Comptabilité sur le serveur de fichiers est inaccessible depuis 8h. "
        "Message : 'Le chemin réseau est introuvable.' Les autres partages fonctionnent normalement.",
        "partage_reseau_inaccessible", "reseau", "normale", "ouvert", mmartin, created_days_ago=0)
    history(t38, mmartin, "création", None, "ouvert", days_ago=0)

    t39 = ticket("SAP très lent au démarrage - 30 secondes pour ouvrir",
        "Le module SAP FI/CO met désormais 25-30 secondes à s'ouvrir contre 5 secondes habituellement. "
        "Problème apparu après la mise à jour SAP GUI 7.70 Patch 4 déployée vendredi.",
        "application_lente", "logiciel", "normale", "en_cours", mmartin, jdupont, created_days_ago=2)
    history(t39, mmartin, "création", None,       "ouvert",   days_ago=2)
    history(t39, jdupont, "statut",   "ouvert",   "en_cours", days_ago=1)

    t40 = ticket("Écran externe sans signal - poste Mme Renard",
        "L'écran externe Dell 27\" du poste de Mme Renard (bureau 412) n'affiche rien depuis ce matin. "
        "Le câble DisplayPort a été remplacé sans amélioration. L'écran intégré du laptop fonctionne.",
        "ecran_noir", "materiel", "normale", "ouvert", mmartin, created_days_ago=1)
    history(t40, mmartin, "création", None, "ouvert", days_ago=1)

    t41 = ticket("Clavier sans fil Logitech plus détecté - poste RH",
        "Le clavier sans fil Logitech K780 du poste RH-05 n'est plus reconnu depuis ce matin. "
        "Remplacement des piles effectué, reset Unifying Receiver tenté sans succès.",
        "clavier_souris_defaillant", "materiel", "faible", "resolu", mmartin, jdupont, created_days_ago=3)
    history(t41, mmartin, "création", None,       "ouvert",   days_ago=3)
    history(t41, jdupont, "statut",   "ouvert",   "resolu",   days_ago=2)
    comment(t41, jdupont, "Récepteur USB Unifying défaillant. Remplacement du récepteur effectué. Clavier fonctionnel.", days_ago=2)

    t42 = ticket("Casque Teams sans son depuis mise à jour Windows",
        "Depuis la mise à jour Windows 11 23H2, le casque Jabra Evolve 40 ne produit plus de son "
        "dans Microsoft Teams. Les autres applications audio fonctionnent normalement.",
        "son_defaillant", "logiciel", "faible", "ouvert", mmartin, created_days_ago=2)
    history(t42, mmartin, "création", None, "ouvert", days_ago=2)

    t43 = ticket("uTorrent détecté sur PC-COMPTA-07 - violation politique SI",
        "L'outil de supervision a détecté uTorrent installé et actif sur le poste PC-COMPTA-07 "
        "(M. Roux, comptabilité). Logiciel non autorisé par la politique de sécurité informatique.",
        "logiciel_non_autorise", "securite", "haute", "en_cours", admin, jdupont, created_days_ago=1)
    history(t43, admin,   "création", None,       "ouvert",   days_ago=1)
    history(t43, jdupont, "statut",   "ouvert",   "en_cours", days_ago=0)
    comment(t43, jdupont, "Logiciel désinstallé, utilisateur convoqué par son responsable. Rapport de sécurité transmis à la DRH.")

    t44 = ticket("GlobalProtect erreur 48 - impossible de se connecter",
        "Mme Torres ne peut plus se connecter au VPN GlobalProtect depuis son domicile. "
        "Erreur : 'Portal does not exist (48)'. Fonctionne depuis le réseau interne.",
        "erreur_connexion_vpn", "reseau", "normale", "ouvert", mmartin, created_days_ago=1)
    history(t44, mmartin, "création", None, "ouvert", days_ago=1)

    t45 = ticket("OneDrive bloqué en synchronisation - fichiers non mis à jour",
        "OneDrive affiche 'Traitement des modifications...' depuis 3 jours sans progresser. "
        "Environ 2 Go de fichiers projet en attente de synchronisation. "
        "Aucun message d'erreur explicite.",
        "synchronisation_echouee", "logiciel", "normale", "ouvert", mmartin, created_days_ago=3)
    history(t45, mmartin, "création", None, "ouvert", days_ago=3)

    t46 = ticket("Onduleur baie réseau - alarme batterie faible",
        "L'onduleur APC Smart-UPS 1500 de la baie réseau salle 101 émet une alarme de batterie faible. "
        "Autonomie estimée à 8 minutes. Risque de coupure réseau non contrôlée.",
        "onduleur_defaillant", "materiel", "haute", "en_cours", admin, admin, created_days_ago=0)
    history(t46, admin, "création", None,       "ouvert",   days_ago=0)
    history(t46, admin, "statut",   "ouvert",   "en_cours", days_ago=0)
    comment(t46, admin, "Commande de remplacement batterie passée en urgence. Délai : 48h. Surveillance renforcée.")

    t47 = ticket("Disque C:\\ serveur de fichiers à 98% - espace critique",
        "Le disque système du serveur SRV-FIC-01 est à 98% d'utilisation (197 Go / 200 Go). "
        "Risque imminent d'arrêt des services si le seuil est atteint. Nettoyage ou extension requis.",
        "stockage_plein", "logiciel", "haute", "en_cours", admin, admin, created_days_ago=0)
    history(t47, admin, "création", None,       "ouvert",   days_ago=0)
    history(t47, admin, "statut",   "ouvert",   "en_cours", days_ago=0)
    comment(t47, admin, "Suppression des logs anciens : +12 Go libérés. Analyse des gros fichiers en cours. Extension disque planifiée.")

    t48 = ticket("Email frauduleux imitant le PDG - tentative de virement",
        "Plusieurs employés ont reçu un email usurpant l'identité du PDG (M. Martin) demandant "
        "un virement urgent de 45 000€. L'email provient d'un domaine similaire (entreprlse.fr). "
        "Aucun virement n'a été effectué.",
        "usurpation_identite", "securite", "critique", "en_cours", admin, admin, created_days_ago=0)
    history(t48, admin, "création", None,       "ouvert",   days_ago=0)
    history(t48, admin, "statut",   "ouvert",   "en_cours", days_ago=0)
    comment(t48, admin, "Domaine frauduleux signalé à l'hébergeur. Règle de blocage mail déployée. Sensibilisation équipe finance.")

    t49 = ticket("Tables PostgreSQL corrompues après crash disque",
        "Suite à un crash de disque sur SRV-DB-02, plusieurs tables PostgreSQL de l'application "
        "RH sont corrompues (pg_catalog, schema hr). Erreur : 'invalid page header in block'. "
        "Application RH complètement hors service.",
        "base_donnees_corrompue", "logiciel", "critique", "en_cours", admin, admin, created_days_ago=1)
    history(t49, admin, "création", None,       "ouvert",   days_ago=1)
    history(t49, admin, "statut",   "ouvert",   "en_cours", days_ago=1)
    comment(t49, admin, "Restauration depuis sauvegarde J-1 en cours. Perte de données estimée : données de la journée. DBA prévenu.", days_ago=0)

    t50 = ticket("Teams crashe systématiquement avec Sophos Intercept X",
        "Depuis la mise à jour Sophos Intercept X 2.0.23, Microsoft Teams se ferme brutalement "
        "lors des partages d'écran. Problème reproductible sur 4 postes. Désactivation Sophos = Teams OK.",
        "incompatibilite_logicielle", "logiciel", "normale", "ouvert", mmartin, created_days_ago=4)
    history(t50, mmartin, "création", None, "ouvert", days_ago=4)

    t51 = ticket("Webcam Logitech C920 non détectée en réunion Teams",
        "La webcam Logitech C920 du poste PC-CONF-02 (salle de conf.) n'est plus reconnue "
        "par Teams ni par l'OS. Appareil absent du gestionnaire de périphériques.",
        "camera_defaillante", "materiel", "faible", "ouvert", mmartin, created_days_ago=1)
    history(t51, mmartin, "création", None, "ouvert", days_ago=1)

    t52 = ticket("Coupure fibre Orange - site de Lyon totalement isolé",
        "Le site de Lyon est totalement coupé d'internet depuis 7h suite à une coupure fibre Orange. "
        "80 collaborateurs sans accès internet, cloud et VPN. Équipe Orange estimant la réparation à 4h.",
        "perte_connexion_internet", "reseau", "haute", "en_cours", admin, admin, created_days_ago=0)
    history(t52, admin, "création", None,       "ouvert",   days_ago=0)
    history(t52, admin, "statut",   "ouvert",   "en_cours", days_ago=0)
    comment(t52, admin, "Bascule sur connexion 4G de secours effectuée. Débit limité à 50 Mb/s. Orange ETA : 11h30.")

    t53 = ticket("Microsoft 365 dégradé - SharePoint et Teams inaccessibles",
        "Depuis 9h15, SharePoint Online et Teams sont inaccessibles pour tous les utilisateurs. "
        "Incident référencé sur le portail Microsoft Service Health (MO782341). Aucune action de notre côté.",
        "interruption_cloud", "reseau", "haute", "ouvert", admin, created_days_ago=0)
    history(t53, admin, "création", None, "ouvert", days_ago=0)

    t54 = ticket("Impossible de se connecter au portail RH - erreur 401",
        "Depuis ce matin, plusieurs utilisateurs reçoivent une erreur 401 (Unauthorized) "
        "en tentant de se connecter au portail RH en ligne. Le portail demande une réauthentification "
        "à chaque accès. Problème SAML/ADFS suspecté.",
        "erreur_authentification", "logiciel", "normale", "ouvert", mmartin, created_days_ago=1)
    history(t54, mmartin, "création", None, "ouvert", days_ago=1)

    # ── Nouvelles demandes ────────────────────────────────────────────────────

    t55 = ticket("Extension quota OneDrive équipe direction - 1 To vers 5 To",
        "Les 3 membres de l'équipe direction ont atteint leur quota OneDrive (1 To). "
        "Demande d'extension à 5 To par utilisateur pour stocker les projets stratégiques.",
        "demande_extension_stockage", "logiciel", "faible", "ouvert", mmartin, created_days_ago=2)
    history(t55, mmartin, "création", None, "ouvert", days_ago=2)

    t56 = ticket("Redirection email M. Bernard vers M. Durand - départ retraite",
        "M. Bernard part en retraite le 31/05. Merci de rediriger ses emails vers son successeur "
        "M. Durand pour une durée de 6 mois, puis de créer un alias permanent.",
        "demande_redirection_mail", "logiciel", "faible", "resolu", admin, jdupont, created_days_ago=8)
    history(t56, admin,   "création", None,       "ouvert",   days_ago=8)
    history(t56, jdupont, "statut",   "ouvert",   "resolu",   days_ago=6)
    comment(t56, jdupont, "Règle de redirection Exchange configurée. Alias bernard@entreprise.fr conservé 6 mois.", days_ago=6)

    t57 = ticket("Création groupe AD 'Projet OMEGA' avec accès NAS et SharePoint",
        "Le chef de projet M. Lévy demande la création d'un groupe de sécurité AD pour le projet OMEGA "
        "(8 membres). Accès requis : dossier NAS \\\\SRV-FIC\\PROJETS\\OMEGA et site SharePoint projet.",
        "demande_groupe_securite", "reseau", "faible", "ouvert", admin, created_days_ago=1)
    history(t57, admin, "création", None, "ouvert", days_ago=1)

    t58 = ticket("Dossier partagé 'Architecture 2026' sur NAS - équipe technique",
        "L'équipe technique (6 personnes) a besoin d'un dossier partagé pour le projet Architecture 2026. "
        "Emplacement souhaité : \\\\SRV-FIC\\PROJETS. Droits : lecture-écriture pour l'équipe, lecture seule pour la direction.",
        "demande_partage_reseau", "reseau", "faible", "en_cours", mmartin, jdupont, created_days_ago=3)
    history(t58, mmartin, "création", None,       "ouvert",   days_ago=3)
    history(t58, jdupont, "statut",   "ouvert",   "en_cours", days_ago=2)

    t59 = ticket("Restauration fichier Excel budget 2026 supprimé par erreur",
        "Mme Petit a supprimé par erreur le fichier 'Budget_2026_V3_FINAL.xlsx' de son bureau "
        "hier soir. La corbeille a été vidée. Besoin de restauration depuis la sauvegarde NAS.",
        "demande_restauration", "logiciel", "normale", "resolu", mmartin, jdupont, created_days_ago=2)
    history(t59, mmartin, "création", None,       "ouvert",   days_ago=2)
    history(t59, jdupont, "statut",   "ouvert",   "resolu",   days_ago=1)
    comment(t59, jdupont, "Fichier restauré depuis la sauvegarde de 22h. Version J-1 récupérée et transmise à l'utilisatrice.", days_ago=1)

    t60 = ticket("Kit télétravail pour Mme Faure - commerciale itinérante",
        "Mme Faure rejoint l'équipe commerciale le 03/06 avec un contrat en télétravail partiel (3j/5). "
        "Besoin : dock USB-C, écran portable 15\", souris sans fil et sac de transport.",
        "demande_tele_travail", "materiel", "faible", "ouvert", mmartin, created_days_ago=2)
    history(t60, mmartin, "création", None, "ouvert", days_ago=2)

    t61 = ticket("Remplacement PC vétuste direction - HP EliteBook 840 G3",
        "Le PC de M. Renault (Direction Administrative) a 7 ans et est devenu inutilisable. "
        "RAM insuffisante (4 Go), disque HDD très lent. Demande de remplacement par un modèle récent.",
        "demande_poste_remplacement", "materiel", "normale", "en_cours", admin, jdupont, created_days_ago=5)
    history(t61, admin,   "création", None,       "ouvert",   days_ago=5)
    history(t61, jdupont, "statut",   "ouvert",   "en_cours", days_ago=4)
    comment(t61, jdupont, "HP EliteBook 840 G10 commandé. Arrivée prévue dans 5 jours. Migration des données planifiée.", days_ago=3)

    t62 = ticket("Mise en service imprimante couleur A3 - service Marketing",
        "Le service Marketing a reçu une nouvelle imprimante Canon imageRUNNER C3226i. "
        "Merci de procéder à la mise en service réseau, installation des pilotes sur les 6 postes "
        "du service et configuration des bacs papier.",
        "demande_mise_en_service", "imprimante", "normale", "ouvert", admin, created_days_ago=1)
    history(t62, admin, "création", None, "ouvert", days_ago=1)

    t63 = ticket("Chiffrement BitLocker sur laptops RH et Finance",
        "Dans le cadre de la politique RGPD, les 8 laptops du service RH et Finance doivent être "
        "chiffrés avec BitLocker. Clés de récupération à centraliser dans Azure AD.",
        "demande_chiffrement", "securite", "normale", "en_cours", admin, jdupont, created_days_ago=6)
    history(t63, admin,   "création", None,       "ouvert",   days_ago=6)
    history(t63, jdupont, "statut",   "ouvert",   "en_cours", days_ago=5)
    comment(t63, jdupont, "4/8 laptops chiffrés. Clés sauvegardées dans Azure AD. Suite prévue demain.", days_ago=2)

    t64 = ticket("Activation MFA Microsoft 365 pour toute la direction",
        "Suite à la recommandation de l'audit de sécurité, l'authentification MFA doit être "
        "activée pour les 5 comptes de la direction. Utilisation de l'application Authenticator.",
        "demande_double_authentification", "securite", "faible", "ouvert", admin, created_days_ago=3)
    history(t64, admin, "création", None, "ouvert", days_ago=3)

    t65 = ticket("Révision des droits AD - service Finance - départs et mutations",
        "Suite à 2 départs et 1 mutation au service Finance en mai, une révision des droits "
        "Active Directory est nécessaire. Liste des accès à révoquer et à créer jointe.",
        "demande_revision_droits", "securite", "normale", "en_cours", admin, admin, created_days_ago=4)
    history(t65, admin, "création", None,       "ouvert",   days_ago=4)
    history(t65, admin, "statut",   "ouvert",   "en_cours", days_ago=3)
    comment(t65, admin, "Comptes des partants désactivés. Droits du muté en cours de mise à jour.", days_ago=2)

    t66 = ticket("Téléphone IP Cisco pour nouveau bureau commercial 215",
        "Le bureau 215 (open space commercial) vient d'être attribué à M. Lambert. "
        "Merci d'installer et configurer un téléphone IP Cisco 7942 avec le numéro de poste 2215.",
        "demande_telephone_ip", "telephonie", "faible", "ouvert", mmartin, created_days_ago=1)
    history(t66, mmartin, "création", None, "ouvert", days_ago=1)

    t67 = ticket("Nettoyage et optimisation PC de M. Petit - bureau 108",
        "Le PC de M. Petit est très lent au quotidien. Beaucoup de programmes au démarrage, "
        "peu d'espace disque, logiciels obsolètes. Demande de nettoyage complet et optimisation.",
        "demande_nettoyage_poste", "logiciel", "faible", "resolu", mmartin, jdupont, created_days_ago=7)
    history(t67, mmartin, "création", None,       "ouvert",   days_ago=7)
    history(t67, jdupont, "statut",   "ouvert",   "resolu",   days_ago=5)
    comment(t67, jdupont, "Démarrage optimisé (8 → 2 programmes), 15 Go libérés, pilotes à jour. Temps démarrage : 45s → 18s.", days_ago=5)

    t68 = ticket("Migration données ancien serveur SRV-OLD vers NAS Synology",
        "Le serveur SRV-OLD doit être décommissionné fin juin. 800 Go de données doivent être "
        "migrés vers le NAS Synology DS1823xs+ avec remapping des droits NTFS.",
        "demande_migration_donnees", "reseau", "normale", "en_cours", admin, admin, created_days_ago=10)
    history(t68, admin, "création", None,       "ouvert",   days_ago=10)
    history(t68, admin, "statut",   "ouvert",   "en_cours", days_ago=8)
    comment(t68, admin, "Migration 340 Go / 800 Go effectuée. Vérification des droits NTFS en cours. ETA : 3 jours.", days_ago=3)

    t69 = ticket("Formation anti-phishing pour le service comptabilité",
        "Suite à 2 incidents de phishing en mai, le RSSI demande une formation de sensibilisation "
        "pour les 12 personnes du service comptabilité. Format : 2h présentiel + simulation de phishing.",
        "demande_formation_securite", "securite", "faible", "ouvert", admin, created_days_ago=3)
    history(t69, admin, "création", None, "ouvert", days_ago=3)

    t70 = ticket("Mise à jour firmware switch HP ProCurve - étage 2",
        "Le switch HP ProCurve 2530-24G de l'étage 2 tourne sur un firmware obsolète (YA.16.02). "
        "Mise à jour vers YA.16.10 recommandée pour corriger 3 CVE critiques. "
        "Intervention à planifier en dehors des heures ouvrées.",
        "demande_mise_a_jour_firmware", "reseau", "faible", "en_cours", admin, jdupont, created_days_ago=5)
    history(t70, admin,   "création", None,       "ouvert",   days_ago=5)
    history(t70, jdupont, "statut",   "ouvert",   "en_cours", days_ago=4)
    comment(t70, jdupont, "Firmware téléchargé et validé. Intervention planifiée samedi 01/06 à 7h00.", days_ago=2)

    t71 = ticket("Configuration écran interactif salle Alpha - Teams Rooms",
        "La salle de réunion Alpha vient d'être équipée d'un écran interactif Samsung Flip 4. "
        "Besoin de configurer Microsoft Teams Rooms, le partage sans fil et la connexion HDMI.",
        "demande_salle_reunion", "materiel", "faible", "ouvert", admin, created_days_ago=2)
    history(t71, admin, "création", None, "ouvert", days_ago=2)

    t72 = ticket("Mise à jour signatures email - nouveau logo et charte graphique",
        "Suite au rebranding de l'entreprise, toutes les signatures email doivent être mises à jour "
        "avec le nouveau logo, les nouvelles couleurs et le nouveau slogan. À déployer pour les 45 utilisateurs.",
        "demande_signature_mail", "logiciel", "faible", "resolu", admin, jdupont, created_days_ago=12)
    history(t72, admin,   "création", None,       "ouvert",   days_ago=12)
    history(t72, jdupont, "statut",   "ouvert",   "resolu",   days_ago=9)
    comment(t72, jdupont, "Template déployé via script PowerShell sur les 45 boîtes. Vérification effectuée sur 5 postes.", days_ago=9)

    t73 = ticket("Export tickets résolus Q1 2026 pour bilan DSI trimestriel",
        "Le DSI demande un export complet des tickets résolus du 01/01 au 31/03/2026 "
        "avec les indicateurs : délai de résolution, type, priorité et technicien assigné.",
        "demande_rapport_activite", "logiciel", "faible", "ouvert", admin, created_days_ago=1)
    history(t73, admin, "création", None, "ouvert", days_ago=1)

    t74 = ticket("Déploiement Microsoft Defender for Endpoint sur 15 nouveaux postes",
        "Les 15 postes récemment livrés ne disposent pas encore de Defender for Endpoint. "
        "Merci de procéder au déploiement et à l'intégration dans la console Sécurité M365.",
        "demande_antivirus", "securite", "faible", "en_cours", admin, jdupont, created_days_ago=4)
    history(t74, admin,   "création", None,       "ouvert",   days_ago=4)
    history(t74, jdupont, "statut",   "ouvert",   "en_cours", days_ago=3)
    comment(t74, jdupont, "10/15 postes enrôlés dans Defender. 5 restants planifiés pour demain.", days_ago=1)

    t75 = ticket("Scan de vulnérabilités avant audit de certification ISO 27001",
        "L'audit de certification ISO 27001 est prévu fin juin. Un scan de vulnérabilités complet "
        "de l'infrastructure (serveurs, postes, équipements réseau) est requis. "
        "Outil préconisé : Nessus Professional.",
        "demande_scan_securite", "securite", "normale", "en_cours", admin, admin, created_days_ago=8)
    history(t75, admin, "création", None,       "ouvert",   days_ago=8)
    history(t75, admin, "statut",   "ouvert",   "en_cours", days_ago=7)
    comment(t75, admin, "Scan Nessus terminé sur les serveurs (43 hôtes). Rapport en cours de rédaction. Postes à scanner la semaine prochaine.", days_ago=2)

    t76 = ticket("Accès RDP serveur applicatif SRV-APP-01 pour équipe projet",
        "L'équipe projet SIGMA (4 personnes) a besoin d'un accès bureau à distance (RDP) "
        "au serveur SRV-APP-01 pour déployer et tester l'application métier en développement.",
        "demande_connexion_bureau_distant", "reseau", "faible", "ouvert", mmartin, created_days_ago=2)
    history(t76, mmartin, "création", None, "ouvert", days_ago=2)

    t77 = ticket("Accès SAP module Finance (FI/CO) pour Mme Legrand - mutation",
        "Mme Legrand vient d'être mutée au service Finance. Elle a besoin d'un accès au module "
        "SAP FI/CO avec les profils : FB03 (affichage pièces), FK03 (affichage fournisseurs), F110.",
        "demande_acces_applicatif", "logiciel", "faible", "en_cours", mmartin, jdupont, created_days_ago=3)
    history(t77, mmartin, "création", None,       "ouvert",   days_ago=3)
    history(t77, jdupont, "statut",   "ouvert",   "en_cours", days_ago=2)
    comment(t77, jdupont, "Profils SAP en cours de création avec le gestionnaire SAP. Accès actif sous 24h.", days_ago=1)

    t78 = ticket("Mise en place supervision Zabbix sur 8 nouveaux serveurs",
        "Les 8 serveurs livrés en mai ne sont pas encore surveillés par Zabbix. "
        "Merci d'ajouter ces hôtes avec les templates adaptés (CPU, RAM, disque, services).",
        "demande_supervision", "reseau", "normale", "en_cours", admin, admin, created_days_ago=6)
    history(t78, admin, "création", None,       "ouvert",   days_ago=6)
    history(t78, admin, "statut",   "ouvert",   "en_cours", days_ago=5)
    comment(t78, admin, "5/8 serveurs intégrés dans Zabbix. Alertes mail configurées. 3 serveurs restants cette semaine.", days_ago=2)

    t79 = ticket("Changement MDP planifié - politique renouvellement 90 jours",
        "La politique de sécurité impose un changement de mot de passe tous les 90 jours. "
        "M. Fabre n'a pas effectué le changement et son compte a été bloqué automatiquement. "
        "Merci de débloquer et d'accompagner le changement.",
        "demande_changement_mdp", "logiciel", "faible", "ouvert", mmartin, created_days_ago=0)
    history(t79, mmartin, "création", None, "ouvert", days_ago=0)

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
        ("Réinitialisation de mot de passe", "demande_reinitialisation_mdp",
         "Processus sécurisé de réinitialisation du mot de passe utilisateur", [
             (1, "Vérifier l'identité du demandeur", "Confirmer l'identité par appel téléphonique, badge ou validation du responsable hiérarchique."),
             (2, "Vérifier le compte dans l'AD", "Contrôler que le compte est actif, non bloqué et non expiré dans Active Directory."),
             (3, "Réinitialiser le mot de passe", "Générer un mot de passe temporaire conforme à la politique de sécurité (12 car. min., majuscule, chiffre, caractère spécial)."),
             (4, "Forcer le changement à la prochaine connexion", "Activer l'option de changement obligatoire du mot de passe dans les propriétés du compte AD."),
             (5, "Communiquer le mot de passe temporaire", "Transmettre via un canal sécurisé (SMS ou appel direct) — jamais par email en clair."),
             (6, "Vérifier la reconnexion et clore le ticket", "Confirmer avec l'utilisateur que la connexion fonctionne, puis fermer le ticket."),
         ]),
        ("Prise en charge panne réseau", "coupure_reseau",
         "Processus de diagnostic et résolution d'une panne réseau", [
             (1, "Qualifier la panne", "Déterminer le périmètre : un poste, un étage, un site entier. Identifier les premiers utilisateurs touchés et l'heure de début."),
             (2, "Vérifier les équipements réseau", "Contrôler les voyants des switchs, routeurs et bornes WiFi. Vérifier les câbles et les branchements physiques."),
             (3, "Tester la connectivité", "Effectuer des ping, traceroute et test DNS depuis plusieurs points du réseau pour localiser la coupure."),
             (4, "Isoler la cause racine", "Identifier la source : équipement défaillant, saturation de bande passante, boucle réseau, VLAN mal configuré ou panne FAI."),
             (5, "Appliquer la remédiation", "Redémarrer l'équipement défaillant, remplacer un câble ou switch, reconfigurer le VLAN ou basculer sur le lien de secours."),
             (6, "Vérifier le retour à la normale", "Confirmer la connectivité sur l'ensemble du périmètre touché. Tester les services critiques (AD, DNS, accès Internet, serveurs)."),
             (7, "Documenter et clore", "Rédiger le compte-rendu d'incident : cause, actions, durée de l'interruption. Clore le ticket et notifier les utilisateurs."),
         ]),
        ("Prise en charge virus et malware", "virus",
         "Processus de traitement d'une infection virale ou malware sur un poste ou serveur", [
             (1, "Isoler immédiatement le poste infecté", "Déconnecter le poste du réseau (câble et WiFi) sans l'éteindre pour préserver les traces en mémoire. Bloquer le compte utilisateur en parallèle."),
             (2, "Identifier et qualifier la menace", "Relever le nom du malware détecté, sa famille et son vecteur d'infection (email, clé USB, téléchargement). Évaluer si d'autres postes sont potentiellement touchés."),
             (3, "Analyser l'étendue de la compromission", "Inspecter les logs de l'antivirus, du firewall et de l'AD pour détecter des mouvements latéraux, des connexions suspectes ou des transferts de données."),
             (4, "Notifier les parties prenantes", "Informer le RSSI, la direction et si nécessaire la CNIL (en cas de fuite de données personnelles sous 72h). Documenter toutes les actions horodatées."),
             (5, "Nettoyer ou réinstaller le système", "Tenter une désinfection via l'antivirus en mode sans échec. En cas d'échec ou de doute, réinstaller proprement l'OS depuis une image saine."),
             (6, "Restaurer les données et vérifier", "Restaurer les fichiers depuis une sauvegarde antérieure à l'infection. Vérifier l'intégrité des données restaurées avant reconnexion au réseau."),
             (7, "Reconnecter et surveiller", "Reconnecter le poste au réseau après validation. Renforcer la surveillance (EDR, logs) pendant 72h et changer les mots de passe de l'utilisateur concerné."),
             (8, "Rédiger le rapport et corriger les failles", "Documenter l'incident complet, identifier la faille exploitée et appliquer les correctifs (patch, politique, sensibilisation) pour éviter la récidive."),
         ]),
        ("Demande d'accès VPN", "demande_vpn",
         "Processus de création et configuration d'un accès VPN pour travail à distance", [
             (1, "Valider la demande avec le responsable", "Vérifier que le besoin est justifié (télétravail, déplacement, prestataire) et obtenir la validation écrite du responsable hiérarchique."),
             (2, "Vérifier les droits et le profil utilisateur", "Contrôler que le compte AD est actif, que le poste répond aux prérequis sécurité (antivirus à jour, BitLocker activé) et vérifier la charte informatique signée."),
             (3, "Créer le compte VPN", "Créer ou activer le profil VPN sur le concentrateur (Cisco ASA, Fortinet, GlobalProtect). Définir le groupe d'accès, les plages horaires et les ressources accessibles."),
             (4, "Configurer le client VPN sur le poste", "Installer et configurer le client VPN (AnyConnect, GlobalProtect, OpenVPN) avec les paramètres du serveur, le certificat et le profil de connexion."),
             (5, "Activer et tester le MFA", "Configurer l'authentification multi-facteurs (SMS, Authenticator, token) et tester la connexion depuis un réseau externe."),
             (6, "Former l'utilisateur et clore", "Expliquer la procédure de connexion, remettre le guide utilisateur et rappeler les règles d'usage. Fermer le ticket."),
         ]),
        ("Demande d'accès à une ressource", "demande_acces",
         "Processus de traitement d'une demande d'accès à une ressource du système d'information", [
             (1, "Vérifier la légitimité de la demande", "Contrôler que la demande est justifiée par le besoin métier et validée par le responsable hiérarchique de l'utilisateur."),
             (2, "Vérifier les droits existants", "Consulter les accès actuels de l'utilisateur dans l'AD et les applications cibles pour éviter les doublons ou conflits de droits."),
             (3, "Vérifier la conformité sécurité", "S'assurer que l'attribution de cet accès respecte la politique de sécurité et le principe du moindre privilège. Alerter le RSSI si nécessaire."),
             (4, "Attribuer les droits d'accès", "Ajouter l'utilisateur aux groupes AD, rôles applicatifs ou ACL correspondants selon la ressource demandée (dossier réseau, application, VPN, etc.)."),
             (5, "Tester et valider l'accès", "Vérifier que l'utilisateur peut accéder à la ressource avec les bons niveaux de droits (lecture, écriture, administration)."),
             (6, "Notifier et clore", "Informer l'utilisateur que son accès est opérationnel. Documenter l'attribution dans le journal des accès et fermer le ticket."),
         ]),
        ("Création de compte utilisateur", "demande_creation_compte",
         "Processus de création d'un nouveau compte utilisateur dans le système d'information", [
             (1, "Vérifier et collecter les informations", "Recueillir nom, prénom, service, responsable, date d'arrivée, rôle et liste des accès applicatifs nécessaires. Vérifier la validation du responsable."),
             (2, "Créer le compte Active Directory", "Créer le compte AD avec l'identifiant selon la convention de nommage, définir un mot de passe temporaire et placer le compte dans les OU et groupes adéquats."),
             (3, "Créer la boîte mail", "Créer la boîte Exchange/Microsoft 365, configurer le nom d'affichage, les alias et ajouter l'utilisateur aux listes de diffusion de son service."),
             (4, "Attribuer les licences logicielles", "Affecter les licences Microsoft 365, logiciels métier et outils requis selon le profil de poste."),
             (5, "Créer les accès applicatifs", "Ouvrir les comptes sur chaque application métier requise (ERP, CRM, intranet, etc.) avec les profils et droits correspondant au rôle."),
             (6, "Communiquer les identifiants", "Transmettre les identifiants de connexion via un canal sécurisé. Informer l'utilisateur de la procédure de changement du mot de passe temporaire."),
             (7, "Vérifier et clore", "Confirmer que le compte fonctionne sur tous les accès requis. Documenter la création dans l'outil de gestion du parc et fermer le ticket."),
         ]),
        ("Demande de matériel informatique", "demande_materiel",
         "Processus de traitement d'une demande de matériel informatique", [
             (1, "Valider le besoin avec le responsable", "Vérifier que la demande est justifiée et validée par le responsable hiérarchique de l'utilisateur."),
             (2, "Vérifier le stock disponible", "Consulter l'inventaire du parc matériel. Si le matériel est disponible en stock, passer directement à l'étape 4."),
             (3, "Lancer la commande fournisseur", "Établir le bon de commande, le faire valider par les achats et le transmettre au fournisseur. Suivi du délai de livraison."),
             (4, "Réceptionner et inventorier le matériel", "Vérifier la conformité de la livraison, affecter un numéro d'inventaire et enregistrer le matériel dans l'outil de gestion du parc."),
             (5, "Préparer et configurer le matériel", "Installer les pilotes, logiciels requis, appliquer la politique de sécurité et joindre au domaine si nécessaire."),
             (6, "Remettre le matériel à l'utilisateur", "Livrer le matériel, faire signer le bon de remise et former l'utilisateur à son utilisation si besoin."),
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
