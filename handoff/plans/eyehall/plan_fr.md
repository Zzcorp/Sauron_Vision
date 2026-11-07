# Barad-dûr : la page qui s'ouvre après l'animation de chargement

Proposition du 7 novembre 2026, revue le même jour après deux relectures critiques. Rien n'est encore construit. La maquette tourne sur des données inventées (EURUSD, XAUUSD, NAS100…), jamais les tiennes. C'est le même portefeuille fictif que dans la maquette de l'Operations Center, pour que les planches se comparent.

**Où regarder :** la vidéo de 8 secondes (`shots/mock_1440.webm` : la fin de ton intro, le passage de relais, puis des événements), la maquette animée (`eyehall_mock.html`) et la planche 5 de l'aperçu (`Eye.dc.html`).

## Ce qu'on garde : ton animation de chargement, telle quelle

- L'intro ne bouge pas : même look, même durée (entre 5 et 8 secondes environ, elle varie un peu à chaque fois), même bouton Skip, même règle « une fois ». Une précision honnête : cette règle vit dans ta session Sauron, qui dure deux semaines. En pratique, l'intro joue donc une fois par connexion, et on n'y touche pas.
- Seule sa destination change. À la fin, au lieu d'aller à l'Operations Center, elle t'amène à Barad-dûr. Trois lignes changent, et seulement leur adresse :
  - la fin de l'animation ;
  - le bouton Skip ;
  - une deuxième connexion dans la même session.
- La ligne de la fin transmet en plus où en est l'animation (son horloge et la position de ta souris). Barad-dûr démarre ainsi sur la dernière image de l'intro : mesuré sur la vraie intro, l'œil reste à sa place à moins d'un demi-pixel près.

## Le nom

**Barad-dûr**, la tour au sommet de laquelle veille l'Œil. Il faut un nom à part : « Eye » désigne déjà la page /eye/, le flux temps réel, la voix Telegram et la couleur verte, et l'Oculus existe aussi. L'adresse sera /barad-dur/. Tu la rouvres depuis la barre latérale (premier lien d'Amon Hen).

## Ce que tu verras

- **Le passage de relais.** Les particules de l'intro et son petit « 100% » s'effacent d'un coup ; ses mots, Skip compris, s'estompent en un tiers de seconde. SAURON glisse vers le coin en haut à gauche, l'œil descend au centre et s'éveille (l'iris passe au vert vif). L'anneau de la journée se dessine, les pages arrivent étape par étape, puis les routes et les deux panneaux. Tout est en place en moins de 2 secondes.
- **En haut, d'abord ce qui a besoin de toi :** « NEED YOU ⨯ 2 alarms · 6 watch », les mêmes alarmes que la Horde et l'Operations Center, avec un lien vers l'Operations Center. Puis le kill switch (« ready · 7 d quiet », ou « fired » en corail avec l'heure), l'état du flux eToro, REAL ARMED, l'horloge, la cloche, le cadenas et ton menu (Profile, Setup… et Log out).
- **Au centre, l'œil vivant.** Il respire au rythme de l'intro, il regarde la page que tu pointes, et il s'illumine quand un ordre est exécuté ou clôturé, dans n'importe quel monde. Au plus une fois toutes les 2 secondes : un kill switch ou une rafale de clôtures ne le fait pas clignoter. Un clic sur l'œil t'ouvre l'Operations Center.
- **Autour de l'œil, l'anneau de la journée de Sauron :** SEE, THINK, DECIDE, ACT, WATCH, TELL, LEARN, avec les mêmes signes que l'Oculus et l'Operations Center (« ● live », « ▲ stale », « ✕ broken »…). ACT est en bas. Le haut reste ouvert : c'est la nuit, qui ramène LEARN vers THINK.
- **Les pages autour de l'anneau.**
  - 20 pages, rangées par étape. Chacune affiche son nom et un vrai chiffre, par exemple « Signals : 13 on the rail ». Un clic ouvre la page.
  - Sur un écran de moins de 1366 px de large, il en reste 14. À 1280 px, les routes sont encore serrées : l'étape E1 mesurera deux solutions et gardera la meilleure.
  - Les 36 autres pages de la barre latérale sont sous leur étape (un clic sur l'étape, un clic sur la page). Les 7 sans étape (Oculus, Operations Center, Profile…) sont en bas et dans ton menu. Et « All pages » (touche /) les liste toutes, avec un champ pour filtrer.
- **20 routes entre les pages**, nommées avec les mots de Sauron : quotes, signals, entries, orders, the book, fills told, closes graded, the night, events ahead… Aucune page n'est isolée.

## Ce qui bouge, et pourquoi

- **Une particule ne part sur une route que quand un vrai événement y passe** : un ordre exécuté, une clôture, un signal, une notification, une nouvelle ou un prix.
  - Exemple : un fill REAL d'un bot va d'Asset Bots au Capital Desk, puis à Positions, puis au Portfolio. Quand les Orcs sont allumés, une particule va aussi jusqu'à l'Orc qui vient de naître.
  - **Rouge plein = argent réel**, or = DEMO, gris = PAPER, orange = alerte d'un garde, blanc = le reste.
  - En E1, les particules sont blanches ; en E2, elles prennent la couleur de leur monde.
- **Aucune particule ne porte de chiffre ni d'étiquette.** Les faux prix du fond actuel disparaissent.
- **Entre deux événements, une dérive verte très lente** glisse sur les routes qui portent des événements. Elle s'endort après une minute sans geste ni événement. Marchés fermés, elle continue et la page le dit ; si la connexion temps réel tombe, elle s'arrête et la page affiche « live updates paused ».
- **Aucun chiffre ne bouge tout seul.** L'œil respire et regarde, le globe du fond tourne et le point « live » bat. Mais aucun chiffre ne défile en compteur : un chiffre qui change reçoit juste un bref fond clair.
- **La maquette condense :** elle montre en 13 secondes des événements qui s'étalent d'habitude sur une journée. En vrai c'est plus calme, et un ordre exécuté est rare : c'est là que l'œil s'illumine.

## À gauche : la performance du portefeuille

- **eToro ne lit qu'un monde à la fois :** ton compte est soit sur REAL, soit sur DEMO. La carte de ce monde-là montre la valeur d'eToro et son âge. L'autre montre sa dernière lecture enregistrée avec son âge, ou un tiret qui dit pourquoi (« not read: eToro reads one world at a time »).
- **REAL en premier :** la valeur du compte eToro et sa variation sur la fenêtre choisie (1D / 7D / 30D / 90D). Juste dessous, trois cases : OPEN NOW, 24 H, FROM HIGH. Puis l'utilisé et le disponible d'eToro, et la courbe.
- **Net des retraits :** la courbe, la variation et le plus haut sont comptés hors retraits payés, et chaque retrait est marqué sur la courbe. Sauron ne connaît pas les dépôts, et la page le dit.
- **PAPER :** le P&L réalisé cumulé, car le simulateur ne garde pas de courbe de valeur.
- **Le P&L** par monde : ouvert, 24 h, 7 j, 30 j. L'ouvert dit sa source avec les mots d'eToro : « eToro's own » ou « ≈ estimate » avec le prix utilisé. Jusqu'à l'étape F4 du flux eToro, ce sera presque toujours une estimation.
- **La devise** est celle de ton compte eToro (des dollars dans la maquette, comme sur l'Operations Center). Le P&L des trades est en dollars.
- **Les trois mondes ne sont jamais additionnés.** Un nombre de positions s'écrit toujours détaillé : « 3 real · 2 demo · 2 paper ».

## À droite : l'activité

- **Les signaux à traiter :** les trois premiers du rail, dans son ordre (ce que tu détiens d'abord), comme sur l'Operations Center ; puis « +10 more · Signals › ».
- **LAST 24 H, un graphique :** une ligne par monde (REAL, DEMO, PAPER), un trait par ouverture, un point par clôture (vert ou corail selon le résultat), une ⨯ pour une alarme.
- **Le taux de gain et l'espérance sur 30 jours,** par monde, avec le nombre de trades. Sous 10 trades : « not judged », sans couleur.
- **La machine :** les bots par monde, les Orcs, le verdict des gardes et le battement (« 64 tasks · 62 on time · ▲ 2 late »).

Chaque chiffre dit sa source, sa fenêtre et son âge. En bas : « Enter the Operations Center » et les raccourcis, cliquables aussi (Entrée pour l'Operations Center, O Oculus, P Positions, S Signals, / All pages), plus 1 à 7 pour ouvrir une étape et Échap.

## Ce qu'elle ne fait pas

- **Aucun bouton d'argent.** CLOSE, TAKE TRADE, le kill switch et les interrupteurs restent sur leurs pages, derrière ton PIN.
- **Aucun appel à eToro ni à un modèle** pour la dessiner : elle lit ce que Sauron a déjà.
- **Aucun faux chiffre.** Un chiffre vieux montre son âge ; un chiffre absent est un tiret qui dit pourquoi.
- **Elle ne remplace pas l'Operations Center :** c'est l'entrée. Elle se met en pause quand l'onglet est caché.
- **Le verrou est respecté :** quand ta session se verrouille, la page cache tout aussitôt et passe à l'écran du PIN. Ton PIN te ramène à Barad-dûr.

## Sur téléphone

En haut, NEED YOU puis l'œil, en petit. Juste dessous, la ligne REAL : la valeur du compte, OPEN NOW, 24 H et FROM HIGH. Puis les pages en grille par étape (de grandes cases faciles à toucher ; chaque étape ouvre ses autres pages), puis les panneaux. Pas de routes ni de particules. Un bouton « Enter the Operations Center » reste en bas.

## Les étapes

| Étape | Ce que tu auras | Quand |
|---|---|---|
| E0 | Ce design, la maquette animée, la vidéo et la planche 5 dans l'aperçu ; Sauron ne change pas | Maintenant |
| E1 | La vraie page sur tes vraies données : le passage de relais, l'anneau, les routes, les deux panneaux, NEED YOU, All pages, le verrou, le lien dans la barre latérale ; particules blanches ; l'intro mène à Barad-dûr ; tests écrits d'abord | Après S1a |
| E2 | Les particules à la couleur de leur monde, chaque entrée sur sa route (bot ou ticket), la naissance de l'Orc, et « depuis ta dernière visite » rejoué en 6 secondes au plus | Après E1 |
| E3 | Le P&L calculé par eToro lui-même, position par position, et les prix rafraîchis toutes les 10 secondes environ | Après les étapes F4 et F7 du flux eToro |

## Les OK dont on a besoin

1. **Le nom** « Barad-dûr », ou celui que tu préfères.
2. **L'intro garde tout ;** seule sa destination devient Barad-dûr. Sa dernière ligne transmet aussi où est l'œil, pour que rien ne saute.
3. **« / » (l'adresse racine) reste l'Operations Center.** Barad-dûr est l'entrée après la connexion. Ou tu préfères que « / » y mène aussi ?
4. **Les 20 pages autour de l'œil,** les autres restant sous leur étape et dans « All pages ».
5. **Les particules colorées par monde,** avec le rouge plein pour l'argent réel.
6. **Les pages sont des points fixes, et seuls les événements bougent** (ce que je propose). Ou voulais-tu que les pages elles-mêmes flottent doucement autour de l'œil ?

Si les choix proposés te vont, « 6 okay » suffit, comme pour l'Operations Center.
