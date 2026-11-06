# Sauron au niveau d'eToro : le plan, en clair

Ce que tu as demandé :
1. Que Sauron voie les prix comme eToro, aussi vite qu'eToro. Pas toutes les 5 minutes.
2. Que le passage d'une source de prix à une autre soit parfait par construction : jamais pénalisant, jamais dangereux pour toi.

## Ce que tu verras à la fin du plan

- **Les prix d'eToro lui-même** pour tout ce que tu as, trades ou surveilles chez eToro, dès que Sauron connaît l'identifiant eToro de l'instrument : le prix de vente et le prix d'achat.
  - Ils arrivent par le flux en direct qu'eToro publie pour les développeurs.
  - L'objectif est moins d'une seconde à l'écran, une demi-seconde en général. Il suppose que la mesure M2 confirme que le flux marche avec ta clé. Le trajet d'eToro jusqu'au serveur n'est pas encore mesuré.
  - Qu'ils soient exactement ceux des boutons de l'appli, aucun texte public ne le garantit : on le vérifiera à l'œil pendant M2.
- **Ton gain ou ta perte, comme chez eToro**, en deux temps :
  - **D'abord le chiffre calculé par eToro.** Sauron le relit environ toutes les 11 secondes : l'interface d'eToro pour les développeurs le garde en mémoire 10 secondes et ne le donne pas plus souvent. L'essentiel de l'écart que tu as vu disparaît dès cette étape. Il peut rester les frais, si l'appli les compte autrement : la mesure M3 le dira.
  - **Ensuite, entre deux chiffres d'eToro, un calcul en direct.** Il repart toujours exactement du dernier chiffre d'eToro et ne bouge qu'avec les prix et le taux de change d'eToro.
  - Ce calcul n'est affiché qu'après au moins 20 lectures où la formule retombe à moins d'un demi-centime du chiffre d'eToro. Sinon, tu vois le chiffre d'eToro avec son âge.
  - Si le direct se coupe, la case garde sa dernière valeur, grisée, avec son âge, jusqu'au chiffre d'eToro suivant. Elle ne recule jamais.
- **D'où vient chaque nombre**, à côté de chaque prix et de chaque gain ou perte : « eToro · direct », « eToro · 12 s », « fermé ».
  - Si le flux d'eToro se coupe, la pastille passe au gris dès que le prix n'est plus confirmé (au plus 15 secondes sur le forex), et l'âge grandit sous tes yeux.
  - Si c'est ta propre connexion à Sauron qui se coupe, tu vois « prix en direct en pause ».
- **Une page de santé** qui mesure en continu le retard sur eToro, et combien de fois le gain ou la perte tombe juste au centime.

## Comment les sources se relaient sans jamais te nuire

Chaque garantie ci-dessous arrive avec son étape. D'ici là, Sauron fait ce qu'il fait aujourd'hui.

- **Un seul patron par instrument : eToro.** Pour tout ce que tu as ou surveilles chez eToro, dès que l'identifiant eToro est connu, seul le prix d'eToro compte. Sans identifiant, la source extérieure reste affichée, avec son nom. Cela ne dépend jamais de « qui a écrit en dernier ».
- **Deux chemins, une seule source.** Le prix d'eToro arrive par le flux en direct, et par une lecture ponctuelle de secours.
  - Les deux sont rangés à part. Sauron prend le plus récent selon l'heure donnée par eToro lui-même, une fois vérifié (M2) que les deux chemins donnent la même heure pour le même prix.
  - Changer de chemin ne peut donc ni faire reculer un prix ni inventer un saut : tout changement visible est un prix qu'eToro a donné.
- **Les autres sources (OANDA, Binance, Yahoo…) ne sont plus que des repères**, affichés à part avec leur nom et leur âge.
  - Elles ne valorisent jamais ta position, ne déclenchent jamais un stop ni une alerte, ne fixent jamais la taille d'une entrée et ne bloquent jamais une protection.
  - Le pire qu'elles puissent faire : pousser Sauron à relire tout de suite le prix d'eToro, ou faire refuser une entrée quand elles contredisent fortement eToro.
- **Un prix d'eToro en retard est montré comme en retard.** Ton argent attend ou refuse ; jamais un autre prix ne prend sa place.
- **Tes protections n'attendent jamais un prix** (étapes 2a et 2b).
  - Le bouton FERMER et l'arrêt d'urgence partent sans attendre un prix. Les stops posés chez eToro restent chez eToro.
  - Si eToro répond « trop de demandes » (au-delà de 20 ordres par minute), Sauron renvoie la fermeture après le délai qu'eToro indique. C'est le seul cas où eToro dit qu'un renvoi est sans danger.
  - Un saut de prix isolé, démenti par une relecture, ne déclenche jamais rien.
  - Si le prix de sortie n'est pas encore connu, la sortie est notée « en attente du prix d'eToro ».
  - Ta limite de perte du jour la compte alors comme une perte prudente, jamais comme un gain, en prenant d'abord le dernier chiffre d'eToro pour cette position.
  - Un seul cas reste : une position sans stop pour laquelle on n'a aucun prix. Elle est marquée « non mesurée » et la limite le dit. À partir de l'étape 8, les nouvelles entrées réelles attendent jusqu'à une heure le chiffre d'eToro.
- **Si le flux s'arrête, Sauron revient à ce qu'il fait aujourd'hui.**
  - Il relit eToro comme maintenant, position par position, et gère chaque position sur cette lecture. Jamais une attente là où aujourd'hui Sauron agit.
  - Si la nouvelle surveillance toutes les 15 secondes s'arrêtait, le passage de 5 minutes d'aujourd'hui reprendrait la main tout seul.
- **Tout est enregistré et testé.** Chaque passage d'un état à un autre (direct, secours, retour) laisse une trace. Chaque passage est rejoué en test sur chaque chemin de ton argent avant de toucher à ton argent.

## Les étapes, dans l'ordre

Chaque étape qui touche ton argent arrive éteinte, avec un seul interrupteur par étape. En attendant, un mode observation note ce que Sauron aurait fait, sans le faire. C'est toi qui allumes l'étape avec ton PIN quand les preuves sont là ; tu peux l'éteindre quand tu veux, sans PIN.

| Étape | Ce qui change pour ton argent |
|---|---|
| 1. Le socle et les compteurs | Rien. Sauron compte les problèmes d'aujourd'hui : protections bloquées, FERMER refusé faute de prix, etc. |
| 2a. Les protections ne sont plus bloquées (1 interrupteur) | Une autre source ne bloque plus jamais tes stops ni les soins de tes positions. Un saut de prix isolé est relu. Confirmé : Sauron agit. Démenti : rien ne se passe. Illisible : seules les positions sans stop chez eToro agissent. Chaque cas de ce genre t'est montré avant que tu allumes. |
| 2b. Fermer sans attendre un prix (1 interrupteur) | FERMER et l'arrêt d'urgence partent sans attendre un prix ; une fermeture refusée pour « trop de demandes » est renvoyée. Ta limite de perte du jour compte les sorties encore sans prix. |
| 3. Les outils de mesure | Rien : ils servent aux mesures décrites plus bas. |
| 4. Le gain ou la perte calculé par eToro, à l'écran, toutes les 11 secondes environ | Rien : affichage seulement. |
| 5. Les autres sources arrêtent de mentir (1 interrupteur) | Plus de prix de la veille présenté comme frais, et les horaires d'hiver sont justes. Moins de faux refus d'entrée. Plus aucune taille calculée sur le cours de la veille présenté comme frais (le repli sur une bougie de moins de 6 heures reste jusqu'à l'étape 10b). |
| 6. Le flux eToro en observation | Rien, vraiment rien : il n'écrit rien de ce que tes décisions lisent. Pendant au moins 5 jours de marché, Sauron compare en silence le direct et la lecture de secours. |
| 7. L'écran au niveau d'eToro | Rien : affichage seulement. Objectif : les prix en moins d'une seconde. Le gain ou la perte en direct n'est affiché que s'il tombe juste au centime ; sinon, le chiffre d'eToro avec son âge. |
| 8. Les sorties comptées au vrai prix d'eToro (1 interrupteur) | Si la mesure M4 montre qu'eToro donne le prix exécuté, ton résultat réalisé, tes R et ta limite du jour deviennent ceux d'eToro. Sinon, Sauron prend l'historique d'eToro, puis note « en attente ». Aujourd'hui, ces chiffres sont environ un demi-écart de prix plus flatteurs que la réalité ; la limite du jour peut donc se déclencher un peu plus tôt, mais sur la vérité. |
| 9. Stops et soins sur le bon côté du prix, toutes les 15 secondes (1 interrupteur) | Les niveaux que Sauron gère lui-même se décident, pour un achat, sur le prix de vente d'eToro, celui auquel eToro valorise la position. Toutes les 15 secondes au lieu de toutes les 5 minutes. Si le direct manque, chaque position garde la relecture d'aujourd'hui. |
| 10a. Les entrées au vrai prix d'achat ou de vente (1 interrupteur) | La taille est calculée sur le prix d'achat (ou de vente) affiché par eToro, celui auquel l'ordre doit s'exécuter. Un peu plus de refus quand les prix d'eToro sont en retard. |
| 10b. Le taux de change d'eToro (1 interrupteur) | La taille et la valeur de tes positions utilisent le taux de change d'eToro, du côté prudent. |
| 11. Le reste (un interrupteur et une étape chacun) | Alertes, posture du marché, Orcs, positions papier, valeur du portefeuille et gardien Morgul passent sur les prix d'eToro. En tout dernier, Sauron arrête d'écrire les prix d'eToro dans son ancienne table de cotations (la solution provisoire, voir plus bas). |
| 12. Le flux privé d'eToro, comme simple signal (1 interrupteur) | Les confirmations d'ordres et de fermetures arrivent plus tôt. |
| 13. En option : réagir en 1 à 2 secondes (1 interrupteur) | Les niveaux que Sauron gère lui-même réagissent en 1 à 2 secondes au lieu de 15. |

Les étapes 2a, 2b, 3 et 5 peuvent avancer en même temps, juste après la première. Je te conseille d'allumer 2a en premier, puis 2b.

## La solution provisoire déjà en route

La branche du budget prépare, sans l'avoir encore enregistrée, une relecture des prix d'eToro toutes les 30 secondes pour tes positions réelles. Elle les écrit dans la table de cotations de Sauron. Elle aide déjà : tes positions sont valorisées sur le prix d'eToro, et non plus sur Yahoo.

Deux limites à connaître :
- Là où un flux OANDA, Binance ou Finnhub tourne, ce flux garde la main, et la relecture d'eToro ne s'affiche pas.
- Le gain ou la perte reste une estimation, calculée avec le taux de change figé à l'ouverture, et marquée comme telle.

Le plan la garde jusqu'à la fin de l'étape 11, parce que plusieurs parties de Sauron s'appuieront sur elle d'ici là.

## Ce que tu dois lancer d'abord

Tout se fait sur le serveur, en démo d'abord, et en lecture seule : les commandes ne passent aucun ordre, n'affichent aucune clé et aucun chiffre de ton compte. Seules quelques petites positions démo, ouvertes et fermées à la main par toi, servent aux mesures. On te donnera la ligne exacte à coller pour chaque commande.

1. **La mesure des prix d'eToro** (`etoro_rates_shape`), dès que la correction des virgules est dans la branche du budget. Cinq passages :
   - deux identifiants ;
   - 20 à 100 identifiants ;
   - 20 lectures espacées de 3 secondes ;
   - la nouvelle version de l'interface ;
   - une seule fois l'ancienne écriture des virgules, pour voir ce qu'eToro répond.

   Elle dit si les lectures groupées marchent, si eToro sert des prix déjà gardés en mémoire, et quel est le vrai plafond de lectures.
2. **La sonde du gain ou de la perte, forme seulement** (`etoro_pnl_probe --shape`), juste après la mesure des prix. C'est une seule lecture. Elle dit aussi si les lectures de prix et de compte partagent le même plafond.
3. **La sonde du flux en direct** (`etoro_ws_probe`), après l'étape 3. Les heures sont en UTC, en heure d'hiver (New York a changé d'heure le 1er novembre) :
   - un jour de semaine ;
   - le vendredi de 20 h 00 à 22 h 30, autour de la fermeture ;
   - le dimanche de 21 h 50 à 22 h 40, à la réouverture ;
   - pendant la pause quotidienne, de 21 h 50 à 22 h 20.

   Lance-la aussi une fois en regardant l'appli eToro, pour comparer les prix à l'œil. Puis de nouveau, une heure plus tôt, la première semaine après le passage à l'heure d'été en mars.
4. **La sonde du gain ou de la perte** (`etoro_pnl_probe`). Avant de la lancer, ouvre à la main, en démo, quelques petites positions : un achat et une vente sur une paire cotée hors dollar (en NZD par exemple), un achat sur EURUSD, une action et une crypto. Note aussi si le gain ou la perte de l'appli inclut les frais.
5. **La sonde de fermeture** (`etoro_close_probe`).
   - Avant de la lancer, ferme à la main l'une de ces positions démo : la sonde la retrouve dans l'historique d'eToro.
   - Pour tester la lecture « ordre de fermeture », il faut un numéro qu'eToro ne donne qu'à celui qui envoie la fermeture. La sonde prend donc celui d'une fermeture démo faite par Sauron lui-même : ses preuves démo le gardent.
6. **Un coup d'œil à la mémoire et à l'horloge du serveur**, pendant la sonde du flux.
7. **Une question générale au support de l'interface eToro.** Facultative mais conseillée, sans aucun chiffre ni identifiant : « Une lecture groupée des prix toutes les quelques secondes, seulement quand le flux en direct est coupé, est-elle acceptable ? »
   - Tant qu'on n'a pas la réponse, ou ta décision écrite, la lecture de secours reste à une toutes les 30 secondes au plus, comme eToro le conseille dans ses propres guides.

## Ce qui ne change pas

- **Les stops posés chez eToro restent ta première protection.** Aucun état de prix ne les annule, ne les desserre ni ne les retarde.
- **Rien ne touche ton argent réel** tant que tu n'as pas allumé l'interrupteur correspondant avec ton PIN. Un interrupteur éteint, c'est exactement le Sauron d'aujourd'hui, solution provisoire comprise une fois la branche du budget fusionnée.
- **Les fermetures, les ordres et les déplacements de stop gardent la priorité absolue** sur toutes les lectures de prix.
- **Aucune fermeture ne part d'un message.** Une alerte te donne le lien vers le bouton FERMER ; elle ne ferme jamais rien elle-même.
- **Les bots proposent toujours au même rythme, toutes les 5 minutes**, car leurs bougies ne changent que toutes les 10 minutes. Seule la surveillance des positions ouvertes s'accélère.
- **Les instruments que tu n'as pas chez eToro** gardent leurs sources actuelles.
- **Sauron reste sous les limites d'eToro**, les plus prudentes quand ses textes se contredisent.
  - Il ne lit jamais les prix toutes les secondes. Pour aller vite, il passe par le flux en direct, comme eToro le recommande.
  - La lecture de secours ne descend pas sous 30 secondes sans preuve.
- **Si eToro refusait le flux en direct à Sauron**, tout le reste du plan tiendrait avec la lecture ponctuelle, mais nettement moins vite : un prix toutes les 30 secondes au départ, quelques secondes au mieux après les mesures. L'âge affiché le dirait, et le « même niveau qu'eToro » ne serait alors pas atteint.
