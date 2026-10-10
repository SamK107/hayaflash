from django.urls import path

from partners import admin_views, public_views, views

urlpatterns = [
    # Public : lien de recommandation.
    path("r/<str:code>/", views.referral_link_view, name="partner_referral_link"),
    # Public, par lien prive (jeton) : documents du programme.
    path("partenaires/d/<str:token>/", public_views.document_page, name="partner_doc_page"),
    path("partenaires/d/<str:token>/accepter/", public_views.document_accept, name="partner_doc_accept"),
    path("verifier/<str:code>/", public_views.verify_page, name="partner_verify"),
    path(
        "platform-admin/partenaires/documents/<int:pk>/invalider/",
        admin_views.document_invalidate,
        name="partners_document_invalidate",
    ),
    # Staff uniquement, sous l'espace plateforme.
    path("platform-admin/partenaires/", admin_views.dashboard, name="partners_dashboard"),
    path("platform-admin/partenaires/liste/", admin_views.partner_list, name="partners_list"),
    path("platform-admin/partenaires/contacter/", admin_views.contact, name="partners_contact"),
    path("platform-admin/partenaires/messages/", admin_views.message_list, name="partners_messages"),
    path(
        "platform-admin/partenaires/messages/<int:pk>/",
        admin_views.message_detail,
        name="partners_message_detail",
    ),
    path("platform-admin/partenaires/documents/", admin_views.documents, name="partners_documents"),
    path(
        "platform-admin/partenaires/documents/export.csv",
        admin_views.documents_csv,
        name="partners_documents_csv",
    ),
    path(
        "platform-admin/partenaires/documents/<int:pk>/",
        admin_views.document_detail,
        name="partners_document_detail",
    ),
    path("platform-admin/partenaires/brief/", admin_views.brief, name="partners_brief"),
    path(
        "platform-admin/partenaires/liens/<int:pk>/revoquer/",
        admin_views.link_revoke,
        name="partners_link_revoke",
    ),
    path("platform-admin/partenaires/<int:pk>/lien/", admin_views.link_create, name="partners_link_create"),
    path(
        "platform-admin/partenaires/<int:pk>/acceptation-ecrite/",
        admin_views.written_acceptance,
        name="partners_written_acceptance",
    ),
    path("platform-admin/partenaires/<int:pk>/offrir-pro/", admin_views.offer_pro, name="partners_offer_pro"),
    path("platform-admin/partenaires/<int:pk>/", admin_views.partner_detail, name="partners_detail"),
    path("platform-admin/partenaires/<int:pk>/liberer/", admin_views.release, name="partners_release"),
    path("platform-admin/partenaires/<int:pk>/valider/", admin_views.validate, name="partners_validate"),
    path(
        "platform-admin/partenaires/<int:pk>/versement/",
        admin_views.build_payout,
        name="partners_build_payout",
    ),
    path(
        "platform-admin/partenaires/versements/<int:pk>/payer/",
        admin_views.mark_paid,
        name="partners_mark_paid",
    ),
    path(
        "platform-admin/partenaires/<int:pk>/export-partenaire.csv",
        admin_views.csv_partner,
        name="partners_csv_partner",
    ),
    path(
        "platform-admin/partenaires/<int:pk>/export-interne.csv",
        admin_views.csv_internal,
        name="partners_csv_internal",
    ),
]
