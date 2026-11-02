# Textes pour l'essai du premier grossiste — brouillons du 02/11/2026

Brouillons, **non déployés** et **non validés par un juriste** (PP-11). À adapter avant envoi : les crochets `[...]` sont à remplir.
Ils reprennent les règles réellement appliquées par le module Distrib (`docs/specs/SPEC_03_DISTRIB_V1.md` §15.13 ; `distrib/README.md`).
Contexte : F-167 (essai de 2 mois sans engagement formel) et F-168 (pages légales muettes sur le grossiste).

---

## A. Message au grossiste (WhatsApp)

> Bonjour [prénom],
> Votre compte grossiste HayaFlash est prêt : [identifiant = votre numéro]. Mot de passe provisoire : [à transmettre séparément], à changer à la première connexion.
>
> **Essai de 2 mois, jusqu'au [date de fin d'essai].** Pendant l'essai, HayaFlash ne prend aucune commission. Après, nous convenons ensemble des conditions, par écrit, avant cette date. Ceci n'est pas un contrat : chacun peut arrêter quand il veut.
>
> Comment ça marche :
> • Vous gérez votre catalogue et le stock que vous allouez à chaque revendeur ; les unités non vendues vous sont reprises.
> • Vous livrez. Si une livraison n'a pas pu se faire, déclarez « Pas livré » avec le motif (obligatoire). **Sans déclaration sous 72 h, la commande est considérée comme livrée et payée.**
> • Les marges de vos revendeurs leur sont versées **chaque semaine** par Orange Money, avec la référence du paiement. Le revendeur a 72 h pour confirmer ou contester ; sans réponse, c'est accepté.
> • Plafond : [10 000] FCFA de marges dues par revendeur. Au-delà, les nouvelles allocations sont bloquées ; les commandes en cours ne le sont jamais.
> • HayaFlash ne touche jamais l'argent des ventes. En cas d'écarts répétés, HayaFlash peut suspendre un compte.
>
> Répondez « OK » si ces règles vous conviennent. Je suis là pour toute question.

## B. Message aux revendeurs (WhatsApp)

> Bonjour [prénom],
> [Nom du grossiste] vous propose ses produits sur HayaFlash. Vous les importez depuis son catalogue, puis vous les vendez comme n'importe quelle vente flash.
>
> **Votre plan MEDIUM est offert jusqu'au [date de fin d'essai]** (au lieu de 2 000 FCFA par mois).
>
> À savoir :
> • Le grossiste livre vos clientes. Il voit leur nom, leur numéro et leur adresse de livraison, pour livrer.
> • Votre marge vous est versée **chaque semaine** par le grossiste, par Orange Money. Vous avez 72 h pour confirmer ou contester ; sans réponse, c'est considéré comme accepté.
> • Si une commande n'est pas livrée, le grossiste le déclare avec un motif. Sans déclaration sous 72 h, elle est considérée comme livrée.
> • Plafond de marges dues par revendeur : [10 000] FCFA. Au-delà, vous ne pouvez plus importer de nouveaux produits tant que le grossiste n'a pas payé ; vos commandes en cours continuent.
> • Cet essai n'est pas un contrat : vous pouvez arrêter quand vous voulez.
>
> Répondez « OK » pour confirmer. Je vous aide à faire votre première vente.

---

## C. Pages légales — phrases proposées (F-168)

Ce que voit réellement le grossiste (`templates/distrib/_orders_live.html:11-12`) : nom, numéro de téléphone et **adresse de livraison saisie** de la cliente. Pas la position GPS ni la note vocale, ni le code de confirmation à 4 chiffres. La **référence Orange Money** de la cliente, facultative, est saisie à la confirmation de réception (`templates/distrib/receipt_confirm.html:13`).

**Politique de confidentialité, § 2 « Acheteurs » (nouvelle puce)**
> Si vous confirmez la réception d'une commande, vous pouvez indiquer la référence de votre paiement Orange Money (facultatif), comme preuve de paiement.

**Politique de confidentialité, § 5 « Qui reçoit ces données » (nouvelle puce)**
> **Le grossiste qui livre**, lorsque vous commandez un produit d'une boutique revendeuse approvisionnée par un grossiste partenaire de HayaFlash : il reçoit votre nom, votre numéro de téléphone, votre adresse de livraison et le contenu de la commande, pour livrer. Il voit aussi, si vous l'avez saisie, la référence de votre paiement Orange Money. Il ne les utilise que pour livrer et suivre la commande.

### Avant de déployer ce texte (point d'attention)

- `LEGAL_PRIVACY_VERSION` (`2026-10`) et `LEGAL_LAST_UPDATED` (18/10/2026) sont figés par `core/tests_legal_reality.py:80-81`. Ajouter ces puces **sans** changer la version et la date rendrait la page inexacte ; les changer oblige à mettre à jour ces tests.
- Le numéro de version sert aux acceptations enregistrées (`core/legal.py:54`) : vérifier avec le code d'acceptation qu'un changement de version ne force pas les vendeurs à ré-accepter, avant de le déployer.
- Texte juridique : à faire relire (PP-11). Ne pas toucher à `partners/legal_docs.py` ni à `templates/partners/legal/` (lettres figées).
