# L'Operations Center devient ton bureau de trading

Tu as demandé la même chose pour l'Operations Center. C'est ta page d'accueil, mais aujourd'hui :
- tes positions commencent deux écrans plus bas, après le grand schéma « A DAY OF SAURON » ;
- plusieurs chiffres additionnent REAL, DEMO et PAPER, une position DEMO est même affichée « REAL MONEY », et la pastille rouge « REAL MONEY » compte aussi les bots branchés sur un compte DEMO ;
- « PORTFOLIO VALUE » n'est le solde de personne : c'est le cash tapé dans /setup/ (en EUR), plus la valeur des positions REAL et DEMO (en USD) et le P&L du paper, sans conversion ;
- le « profit factor » affiché est en fait le gain moyen divisé par la perte moyenne ;
- le bouton CLOSE est caché derrière un défilement sur le côté ;
- beaucoup de texte est trop petit et trop pâle.

Voici ce qu'elle devient, dans le style que tu as validé : sombre, Bloomberg × TradingView, à la Sauron. Elle recevra aussi la « couche magique » que tu as demandée : l'Œil vivant, les titres dans la police de Sauron, la lumière verte sur ce qui vit, les braises derrière les cartes. La maquette jointe, avec des données fictives, ne la montre pas encore. Elle montre la page complète (après OC2, avant le flux F4), dans le futur cadre de l'étape S1b. La barre du bas y est celle prévue pour S1b, avec deux propositions faites à S1b : le P&L de chaque monde séparé, et PORTFOLIO sans signe de devise.

## Ce que tu verras, de haut en bas

1. **Une ligne pour tout voir d'un coup d'œil :**
   - les positions qui ont besoin de toi : les alarmes de la Horde (« ⨯ 2 alarmes »), avec à côté le nombre de positions en simple surveillance ;
   - ce qu'eToro dit avoir pour toi : la valeur du compte et le cash disponible, chiffres d'eToro, avec l'âge de la lecture ;
   - le prochain chiffre économique et combien de tes positions il touche (« US CPI 13:30, dans 37 min, touche 7 sur 8 ») ;
   - les signaux sur le rail, et combien touchent tes positions ;
   - le régime du marché selon Sauron, avec son âge ;
   - le battement de la machine, avec les mêmes mots que l'Oculus (« ▲ 2 en retard »), et le lien vers l'Oculus.
2. **Tes trois mondes, côte à côte, jamais additionnés :** REAL, DEMO et PAPER. Chaque carte est exactement la somme de ses lignes dans la table en dessous. Pour chacune :
   - le P&L ouvert, avec ses mots ;
   - le R ouvert et le risque aux stops ;
   - le réalisé sur 24 h, et comment il a été compté (au prix de sortie d'eToro, frais non comptés) ;
   - la ligne du compte. Pour REAL : le P&L du compte selon eToro, la marge utilisée, et ce qu'eToro détient en dehors des lignes de Sauron.

   Juste en dessous, une ligne résume ce qui s'est passé depuis ta dernière visite.
3. **Tes positions, dans une seule table :**
   - le réel d'abord, avec son liseré rouge, puis les plus récentes. Cet ordre ne bouge pas pendant que tu regardes, donc un bouton CLOSE ne se déplace jamais sous ta souris ;
   - sur chaque ligne, le feu de la Horde et ses propres mots, recopiés tels quels : une clôture refusée chez eToro, pas de stop, un chiffre important dans l'heure ;
   - une clôture que Sauron a abandonnée a sa propre ligne, avec le lien vers son histoire ;
   - sous la table, ce qu'eToro détient et que Sauron ne suit pas (par exemple ce que tu as ouvert dans l'app eToro) ;
   - le prix avec sa source et son âge, le P&L avec ses mots, le R et la distance au stop ;
   - CLOSE toujours visible à droite : le même bouton, la même fenêtre et le même PIN qu'aujourd'hui.
4. **Le marché et les signaux, côte à côte :**
   - **Le marché sur ce que tu détiens et ce que tu surveilles :** les événements des prochaines 24 h et les positions qu'ils touchent (avec la règle exacte du « care »), la variation du jour et les news de ce que tu détiens, tes instruments étoilés, et la lecture du cerveau.
   - **Les signaux à jouer :** ceux qui portent sur un symbole que tu détiens, et dans quel monde (« tu le détiens : REAL, short 1,5 ») ; ceux que les bots comptent maintenant ; les nouveaux depuis ta dernière visite. Un clic ouvre la carte dans le rail, où TAKE TRADE et PASS restent.
5. **Les bots et les Orcs, à côté de « depuis ta dernière visite » :**
   - l'état du programme et son dernier tick ;
   - par monde : ce qui a été ouvert, fermé et réalisé sur 24 h ;
   - les entrées refusées par les plafonds d'exposition, et pourquoi ;
   - la santé de chaque bot, d'après son propre tick ;
   - les Orcs en veille : leurs esprits sont allumés, leurs intentions restent en mode ombre, rien n'est placé ;
   - depuis ta dernière visite : les trades, les alertes et les refus.
6. **Le cycle :** les sept étapes (SEE … LEARN) sur une seule ligne. Un clic t'emmène sur l'Oculus (directement à l'étape une fois l'Oculus O2a livré).
7. **Plus bas, à la demande :** la revue (performance, historique, bots, par monde et par période, avec la « PORTFOLIO VALUE » dans son propre cadre et son explication), le grand schéma du cycle (plié), et la liste de chaque tiret avec sa raison.

## Ce qu'il faut savoir sur les chiffres

- **Le P&L de chaque position est pour l'instant une estimation.**
  - Il est affiché « ≈ » et dit quel prix il utilise : le prix d'eToro de moins de 15 min quand il existe, sinon le dernier prix vu chez eToro, ou un flux public.
  - Le P&L propre à eToro, position par position, arrive avec le nouveau flux (F4).
  - Pour DEMO, c'est toujours une estimation jusqu'à F4, car la synchro ne lit que le compte REAL.
  - Seuls les chiffres qu'eToro donne lui-même, et les clôtures comptées au prix d'eToro, sont en vert ou en rouge.
- **« Besoin de toi » ne compte que les alarmes ⨯ de la Horde.** Dans l'heure qui précède un chiffre américain important (CPI, NFP, Fed), presque toutes tes positions passent en ⚠ : c'est la règle de la Horde. Elles sont comptées à côté, pas dedans.
- **Les refus affichés sont ceux des plafonds d'exposition** (thème, devise, secteur). Les limites du livre et le stop journalier ne sont pas enregistrés comme événements, et la page le dit.

## Ce qui se met à jour tout seul

- **Ton argent et tes positions :** la page relit toutes les 30 s, et tout de suite quand un ordre est rempli ou fermé. Les chiffres d'eToro sont relus toutes les 60 s, avec leur âge affiché. Le rafraîchissement attend si une fenêtre est ouverte ou si ta souris est dans la table.
- **Le marché, les signaux, les bots, le cycle et « depuis ta dernière visite » :** toutes les minutes.
- **La revue :** quand tu l'ouvres, pas en continu.
- **Onglet caché ou verrouillé :** la page elle-même ne fait plus aucune requête quand l'onglet est caché ou verrouillé ; le cadre continue jusqu'au chantier P4. Aujourd'hui, la page verrouillée fait même plus de requêtes que la page ouverte, et son rafraîchissement empêche le verrouillage automatique côté serveur. OC0 corrige ce second point.
- **Avec le nouveau flux eToro (F4 puis F7) :** le P&L d'eToro environ toutes les 11 s en REAL quand le marché est ouvert, toutes les 30 s en DEMO, et les prix en direct.

## Ce qui ne change pas

- **Aucun nouveau bouton qui touche à l'argent.**
  - CLOSE et RETRY CLOSE restent les mêmes : mêmes étapes, même fenêtre, même PIN. Seul le RETRY de l'onglet PORTFOLIO devient RETRY CLOSE, comme partout ailleurs.
  - TAKE TRADE reste dans le rail.
  - CLOSE ALL reste sur /positions/, et le kill switch sur sa page, avec ton PIN. L'accueil t'y emmène.
- **REAL, DEMO et PAPER ne sont jamais additionnés.** Un tiret n'est jamais un zéro, et chaque tiret dit pourquoi.
- **Aucun appel** à eToro ni à un modèle d'IA pour afficher la page.
- **Le moteur, les bots, les Orcs, le desk et la gate** voient exactement la même chose qu'avant. Seul l'affichage change.
- **L'Oculus reste la tour de contrôle.** L'accueil ne recopie pas ses blocs (gardes, budget eToro, flux, IA, tâches) : il t'y mène.
- **Rien ne disparaît.** Ce qui quitte l'accueil reste ailleurs, avec un lien : l'exposition par thème, devise et secteur reste sur /eye/ ; les lignes de l'ancien bot crypto aussi ; l'échelle des règles est sur l'Oculus.

## Dans quel ordre

- **OC0, tout de suite (rien à valider) :** les corrections de vérité, dans l'affichage actuel.
  - La position DEMO n'est plus « REAL MONEY ».
  - La pastille rouge « REAL MONEY » ne compte plus les bots d'un compte DEMO.
  - Plus rien n'additionne deux mondes : gains et pertes moyens, profit factor et P&L par classe passent aussi par monde.
  - « PORTFOLIO VALUE » dit enfin ce que c'est, sans signe de devise. La ligne d'eToro est posée à côté, à la même taille ; la mettre en premier et en plus grand, c'est ta décision 2.
  - Le « profit factor » devient le vrai : gains totaux divisés par pertes totales.
  - Chaque montant a deux décimales et sa devise ; chaque chiffre dit sa période et son âge.
  - CLOSE est toujours visible.
  - Les boutons des bots sont cachés pour qui ne peut pas s'en servir.
  - Les onglets sont 60 à 90 % moins lourds, et PORTFOLIO six fois plus rapide sur six mois de données.
- **OC1, après le socle du nouveau style (S1a) :** le nouveau look et le nouvel ordre. La ligne du haut, les trois mondes, la table des positions, le cycle, puis la revue : une seule page au lieu de quatre onglets.
- **OC2 :** le bureau complet. Les feux de la Horde sur chaque position, la clôture abandonnée, ce qu'eToro détient hors de Sauron, le marché, les signaux à jouer, les bots et les Orcs, et « depuis ta dernière visite ».
- **OC3, quand le flux eToro arrive (F4 puis F7) :** le P&L d'eToro et les prix en direct.

## Ce qu'il nous faut de toi

1. Ton OK sur l'ordre des blocs ci-dessus, ou ce qui doit monter.
2. Ton OK pour mettre en premier, et en plus grand, les chiffres d'eToro (valeur du compte, cash disponible), et pour faire descendre « PORTFOLIO VALUE » dans la revue, dans son propre cadre, avec son explication.
3. Ton OK pour plier en bas de page le grand schéma du cycle, THE BEAT et la frise des 24 h. Ils sont fermés par défaut ; un clic les ouvre, et ils restent alors immobiles.
4. Ton OK pour une seule page au lieu de quatre onglets : LIVE réparti dans les blocs, PORTFOLIO, HISTORY et BOTS dans la revue. Tes liens ?tab=... continuent de marcher.
5. Ton OK pour que la page retienne le moment où tu as regardé l'accueil, comme le font déjà les points du menu, pour le bloc « depuis ta dernière visite ». Ce moment avance quand le bloc est resté 5 s à l'écran, ou quand tu cliques « marquer comme lu ». Passer par l'accueil ne suffit pas. Sans ton OK, ce bloc montre les dernières 24 h.
6. Ton OK pour retirer de l'accueil les boutons « Toggle » et « ▶ Tick » des bots. Ils restent sur la page des bots et dans Admin HQ. Aujourd'hui, « Tick » lance un tour de bot sans PIN ni confirmation, et « Toggle » ne dit pas s'il allume ou s'il éteint.

Trois petits chantiers techniques viendront à part, chacun avec sa fiche :
- un index pour accélérer les comptes sur 24 h et 90 jours ;
- l'arrêt des requêtes du cadre quand l'onglet est caché ou verrouillé ;
- en option, garder chaque nuit la valeur du compte eToro, pour afficher sa variation du jour.
