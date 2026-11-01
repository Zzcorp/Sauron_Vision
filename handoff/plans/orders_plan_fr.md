# Ordres à un prix, prix intelligents, programmes, annulation d'une clôture : le plan

**À confirmer d'abord :** par « cancel the closing order », vous voulez pouvoir annuler une clôture en attente (le bouton CLOSE reste), et non retirer la possibilité de clôturer ? Oui ou non.

## Ce que vous et les bots pourrez faire, phase par phase
- **P1, annuler une clôture en attente.** Quand eToro refuse une clôture que la plateforme réessaie, le bouton CANCEL CLOSE garde la position (avec votre PIN). La même règle de clôture est alors suspendue 4, 24 ou 72 h.
  - C'est refusé si plus rien ne gérerait la position ensuite, si la clôture vient de l'arrêt d'urgence, ou si le stop est déjà franchi.
  - Pour une clôture qu'eToro a acceptée et pas encore exécutée (souvent marché fermé), vous l'annulez dans l'appli eToro, et la plateforme note seulement ce que vous dites. Elle ne remettra la ligne « ouverte » que lorsqu'elle saura lire les ordres de clôture d'eToro (P1b).
- **P2, ordres à un prix**, sur le ticket TAKE TRADE et sur celui de l'instrument : limite « au toucher » et stop d'entrée.
  - Leur expiration : fin de séance, une date, ou jusqu'à annulation (30 jours au plus).
  - Au toucher, la plateforme envoie un ordre au marché à travers toutes les barrières des bots, jamais au-delà de votre « pire prix accepté ».
  - Une page Ordres (en cours, en ombre, 48 dernières heures), où vous annulez un ordre, plusieurs ou tous, et déplacez un ordre.
- **P3, prix intelligents.** Sous le champ prix, les niveaux que la plateforme calcule déjà (poches de liquidité, sommets et creux, range asiatique, chiffres ronds), chacun avec sa source et son âge, selon la classe d'actif.
- **P4, programmes.** « Quand ces conditions deviennent vraies, place cet ordre » : un prix qui croise un niveau, une fenêtre horaire, un signal actif.
  - Les limites sont obligatoires, et un programme n'a qu'une idée à la fois.
  - Il tourne en ombre d'abord, noté contre une entrée au marché, puis pour vous ou pour un bot.
- **P5, les bots.** Chaque bot note en ombre l'ordre qu'il aurait posé à un niveau. Une fois son dossier suffisant, il le pose vraiment, avec votre PIN.

## Ce qu'eToro permet, et ce qu'on mesure d'abord sur le compte démo
- eToro peut tenir un ordre « déclenché au toucher », mais seulement du côté favorable, et il n'a jamais été testé avec notre clé. eToro n'a ni stop d'entrée ni expiration.
- L'annulation d'une clôture en file est documentée par eToro, mais jamais appelée.
- **Avant P2 :** lire les prix d'eToro par lot, son quota de requêtes, l'effet d'un identifiant de requête répété, ses ordres en attente après un envoi sans réponse, et ses horaires propres.
- **Avant P1b :** lire puis annuler une clôture en file, dans quatre cas : en file, annulée à la main, annulée par la plateforme, exécutée.
- **Avant l'ordre tenu par eToro :** neuf autres mesures, dont le week-end et le côté du prix comparé.

## Ce qui reste protégé sur l'argent réel
- Un ordre réel à un prix reste en ombre (surveillé et noté, jamais envoyé) tant que vous n'activez pas l'interrupteur « live » avec votre PIN. L'activer n'envoie aucun ordre déjà armé en ombre.
- Au déclenchement, tout est revérifié : stop journalier, plafond de risque, réserve, minimum d'eToro, horaires, prix d'eToro relu et récent, santé du courtier. Ce qui ne peut pas être lu retient l'ordre ; il ne passe jamais.
- Un ordre qu'eToro mettrait en file marché fermé est retiré aussitôt. Il n'est jamais rempli au prix d'ouverture.
- Un envoi resté sans réponse n'est jamais renvoyé. Son risque reste réservé jusqu'à ce que vous ayez vérifié eToro.
- Un ordre posé en papier ou en démo est annulé si le compte passe au réel, et ce passage est refusé tant que des ordres attendent.
- Les clôtures gardent une réserve de requêtes vers eToro que les entrées ne peuvent pas consommer.

## Vos choix
1. Quand eToro ne peut pas tenir l'ordre (le stop d'entrée, et la limite avant mesure), la plateforme le tient-elle ? Proposé : oui en papier et en démo ; en réel, en ombre jusqu'à votre feu vert.
2. Quels actifs ont les prix intelligents en premier ? Proposé : crypto et forex, puis indices et matières premières après mesure, actions en dernier.
3. Les entrées des bots à un niveau : en ombre d'abord, puis en réel, bot par bot, après 30 ordres notés avec une moyenne positive ? Proposé : oui.
4. Un ordre au marché envoyé marché fermé est retiré après 26 h, donc jamais rempli le week-end. On garde cette règle en l'affichant, ou on le laisse attendre l'ouverture ? Proposé : garder et afficher.
5. Les réglages proposés vous conviennent-ils ? « Jusqu'à annulation » s'arrête à 30 jours ; le pire prix par défaut est 0,10 R pour un stop d'entrée et 0,02 R pour une limite ; après votre annulation d'un ordre de bot, ce bot ne le repose pas pendant 12 h, ou jusqu'à son prochain signal.
