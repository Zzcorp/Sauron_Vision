# L'Oculus devient la tour de contrôle

Tu as demandé d'améliorer l'Oculus. Aujourd'hui, c'est une longue colonne de chiffres. La première réponse arrive après deux écrans, en petit gris peu lisible, sans dire si quelque chose cloche. Voici ce qu'il devient, dans le nouveau style que tu as validé : sombre, Bloomberg × TradingView, à la Sauron.

## Ce que tu verras, de haut en bas

1. **Une ligne d'état.** En une seule ligne :
   - tout va bien, ou « 2 choses demandent ton attention » ;
   - l'argent réel est-il armé, et sur combien de bots ;
   - le kill switch : prêt, ou déclenché il y a combien de temps et pourquoi ;
   - les gardes Morgul : calmes, ou une alerte ;
   - les prix : en direct ou en retard ;
   - le cœur de Sauron : sa dernière tâche il y a 40 s ;
   - les bots : LIVE, PAPER, SHADOW, arrêtés ou bloqués ;
   - ce que l'IA a dépensé aujourd'hui ;
   - l'âge de ce que tu lis.
2. **« À toi de voir ».** La courte liste de ce qui ne va pas :
   - le plus grave d'abord, et l'argent réel d'abord ;
   - pour chaque ligne : le pourquoi, depuis quand, et le lien vers la page qui règle le problème.

   Quand tout va bien, une seule ligne dit ce qui a été vérifié.
3. **Le cycle.** Les sept étapes que tu connais déjà sur l'accueil : SEE, THINK, DECIDE, ACT, WATCH, TELL, LEARN.
   - Chacune montre son état (vivante, en retard, cassée, éteinte), sa dernière exécution et deux chiffres du jour.
   - Un clic ouvre la liste de ses tâches. Chaque tâche est jugée sur son propre rythme : une tâche quotidienne n'est pas « en retard » au bout d'une heure.
4. **L'argent est-il protégé ?**
   - **Trois colonnes, jamais additionnées :** REAL, DEMO et PAPER, chacune avec ses positions, son P&L (celui d'eToro quand eToro le donne) et son risque aux stops.
   - **Le compte eToro, avec son âge :** la valeur du compte, la marge utilisée, le cash libre, et ta limite de marge. À 100 %, c'est le cash libre qui décide seul.
   - **La check-list :**
     - chaque position réelle a un stop chez eToro ;
     - aucune clôture bloquée ;
     - la marge sous ta limite ;
     - la perte du jour sous ton stop ;
     - Sauron et eToro d'accord ;
     - le tick des bots à l'heure ;
     - le frein Morgul armé ou non ;
     - le kill switch : son dernier déclenchement, ce qu'il a laissé ouvert, et le lien vers sa page.
5. **Les prix et les requêtes eToro.**
   - Chaque source de prix, et l'âge du prix de chaque instrument que tu détiens.
   - Le budget de requêtes eToro par famille, et la pause « 429 » si eToro nous demande de ralentir. Les clôtures et les ordres ne sont jamais mis en pause.
6. **Ce qui agit et ce qui ne fait que regarder.**
   - les bots ;
   - les 12 interrupteurs d'argent réel ;
   - le desk et les allocateurs, en direct ou en répétition ;
   - les règles par marche de l'échelle ;
   - les Orcs et leurs interrupteurs (ils écrivent, ils ne placent rien) ;
   - le Conseil.
7. **L'IA.** Ce qui est dépensé aujourd'hui, par ligne (le cœur et les Orcs) contre son plafond. Les appels des Orcs et leurs réveils.
8. **La dernière heure.** Ce qui a bougé : ordres, clôtures, refus, alertes des gardes, interrupteurs à PIN, réponses des Orcs.
9. **Plus bas, les cycles lents**, rangés par étape : le scan, les signaux, l'échelle, les personnalités, l'allocation, l'évolution, les backtests, le simulateur face au réel, la confiance, l'horizon.
   - Ce sont les mêmes chiffres qu'aujourd'hui, mais lisibles.
   - Chacun dit sa fenêtre : aujourd'hui, 7 jours, 30 jours ou depuis toujours.
   - L'orange n'apparaît que quand un seuil est franchi, avec ⚠ et des mots.

   Puis la forge (quel code tourne), et la liste nommée de ce qui n'a pas pu être mesuré.

## Ce qui se met à jour tout seul

- **L'argent et la dernière heure :** toutes les 30 s.
- **La ligne d'état, la liste et le cycle :** toutes les minutes.
- **Quand un ordre est rempli ou fermé :** tout se met à jour tout de suite.
- **Quand ça s'arrête :** rien ne tourne quand l'onglet est caché ou verrouillé par ton PIN.
- **Avec le nouveau flux eToro (F7) :** les prix et le P&L d'eToro bougent en direct, sans requête de plus.

## Ce qui ne change pas

- **L'Oculus ne fait rien, il montre.** Aucun bouton n'agit. Le kill switch, CLOSE et les interrupteurs restent sur leurs pages, derrière ton PIN. L'Oculus t'y emmène.
- **Les trois règles restent :**
  - l'interrupteur est à côté du chiffre ;
  - ce que veut dire le chiffre est sur la même ligne ;
  - un tiret n'est jamais un zéro, et chaque tiret est nommé en bas.
- **REAL, DEMO et PAPER ne sont jamais additionnés.** Une estimation le dit.
- **Aucun appel** à eToro ni à un modèle d'IA pour afficher la page.
- **Les pages détaillées restent** ; l'Oculus y mène.
- **Le moteur, les bots, les Orcs, le desk et tes interrupteurs** voient exactement la même chose qu'avant. Seul l'affichage change.

## Deux corrections de chiffres, tout de suite

1. **La colonne « argent réel » comptait aussi tes positions DEMO d'eToro.** Elle ne compte plus que le réel. Dans nos données de test (fictives), le risque « réel » passe de 473,8 à 23,8.
   - Le desk, lui, ne change pas : il compte encore le DEMO jusqu'aux étapes C1-C3, que tu as déjà validées. L'Oculus dit combien de lignes DEMO le desk compte encore.
2. **Ce qui n'est pas encore à échéance n'est plus en orange** : détections, signaux et prévisions.

## Dans quel ordre

- **O0, tout de suite** (rien à valider) : la correction REAL/DEMO, chaque tiret nommé, et une page environ trois fois plus légère (81 → ~30 lectures de la base).
- **O1, après le socle du nouveau style (S1a)** : le nouveau look.
- **O2a** : la tour de contrôle (ligne d'état, liste, cycle, argent, dernière heure).
- **O2b** : ce qui agit, l'IA, les prix et le budget eToro.
- **O3, quand le flux eToro arrive** (F6 puis F7) : les prix en direct, à la qualité d'eToro.

## Ce qu'il nous faut de toi

1. Ton OK sur l'ordre des blocs ci-dessus, ou ce qui doit monter.
2. Ton OK pour que les cycles lents passent sous les blocs du « maintenant », avec leurs explications à un clic.
