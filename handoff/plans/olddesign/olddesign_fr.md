# Refaire tout l'ancien design : ce qui reste, et dans quel ordre

Tu as demandé de refaire tous les éléments de l'ancien design pour qu'ils s'intègrent dans le nouveau. On a fait le tour de Sauron, page par page, sur une copie locale avec des données inventées, puis une relecture a ajouté ce que le premier tour n'avait pas vu (ta fenêtre de connexion sur le Mur, des boutons d'argent de la page Admin, le mode clair…) : il reste **116 éléments** dans l'ancien style.

## Ce qui est encore ancien aujourd'hui

Quatre exemples que tu vois tous les jours :

1. **Le cadre de chaque page.** Trois bandeaux en haut (titre, prix, news) : ta première ligne de contenu commence à 184 points du haut de l'écran. En bas, une barre de 61 points dont une partie des cases est cachée derrière des flèches. Gollum, l'Œil et la Horde flottent par-dessus tes tableaux. *(image 1)*
2. **Le tableau des positions.** Les symboles dans le vert de l'Œil, les quantités à 8 décimales (40.00000000), des lignes de 165 points de haut parce que la ligne de l'Orc s'étale sur 7 lignes en tout petit, et une partie du tableau cachée sur le côté. *(image 3)*
3. **La fenêtre TAKE TRADE.** Les avertissements empilés sur un fond doré (la couleur de DEMO), en petits caractères, sans résumé en haut : il faut descendre pour tous les lire. Le bouton de confirmation est le même pour un achat et pour une vente. *(image 4)*
4. **La page Ops.** Chaque OFF est en corail, la couleur d'une perte, alors qu'éteindre est le sens prudent. TURN ON est un bouton clair et voyant, même pour l'argent réel, sans la pastille REAL à côté. *(image 5)*

Et partout : des étiquettes en 9 points, des reflets verts autour des boutons et des cartes, des icônes de menu qui changent selon l'ordinateur (certaines deviennent des émojis en couleur).

## L'ordre : 25 étapes (26 si tu gardes le mode clair), chacune livrée seule

Chaque étape ne change que l'affichage ; tu reçois les images avant/après à chaque fois. L'ordre suit les pages que tu ouvres le plus (celui proposé dans le plan) : dis-nous si tu en ouvres d'autres plus souvent.

| Étape | Ce qui change pour toi |
|---|---|
| 0 | Rien de visible : un contrôle automatique qui mesure chaque page et refuse tout retour de l'ancien style. |
| 1 à 4 : le cadre | Environ 120 points de hauteur en plus sur chaque écran d'ordinateur. Un seul bandeau en haut, où prix et news continuent de défiler (arrêt au survol). Une barre fine en bas où les cases importantes tiennent toujours, avec Gollum, l'Œil et la Horde rangés dedans. Le Conseil et l'Activité ouverts depuis le bord droit ; la colonne des signaux pousse la page au lieu de la couvrir. Une seule famille d'icônes. Les cartes, menus et panneaux du cadre dans le nouveau style. Un prix qui bouge prend un fond teinté un instant au lieu de briller. |
| 5 : les pièces communes | Sur une cinquantaine de pages d'un coup : étiquettes lisibles, cases de chiffres calmes, cartes qui ne se soulèvent plus en brillant, cases à cocher sobres, un seul style de message après un enregistrement. |
| 6 : ticket et TAKE TRADE | Un résumé « ⚠ N avertissements » en haut de la fenêtre, les avertissements en orange, la confirmation dans la couleur du sens (jade pour un achat, corail pour une vente), la pastille REAL, DEMO ou PAPER dans le titre. Un en-tête d'instrument compact. |
| 7 : les positions | Le tableau tient sans défiler de côté, des quantités normales, des lignes basses (la ligne de l'Orc dans un détail qui se déplie), CLOSE ALL avec le carré ■, une fenêtre de fermeture claire. Sur la page d'une position, la pastille REAL passe en rouge plein (elle est en or aujourd'hui, la couleur de DEMO). |
| 8 : l'accueil | Le Centre d'opérations tel que tu l'as validé : ton argent eToro d'abord, tes positions en haut, une seule page. |
| 9 : signaux et portefeuille | Les mêmes pièces, et des petits graphiques où un gain est jade, avec un camembert en cinq couleurs distinctes. |
| 10 : le graphique | Presque toute la hauteur de l'écran (moins le cadre), une seule rangée d'outils, bougies jade et corail, les prix O H L C dans le graphique, des étiquettes stop et objectif qui ne s'empilent plus. |
| 11 à 15 | Ops (une liste dense et filtrable, OFF en gris, REAL à côté de chaque interrupteur d'argent réel), l'Oculus, les réglages d'argent (formulaires lisibles, le choix du monde chez le courtier expliqué avec ses pastilles), les bots (l'argent réel jamais montré comme une perte), la connexion et le verrou, y compris la fenêtre de connexion et de PIN du Mur, celle où tu arrives après chaque déconnexion (l'Œil gardé, plus de faux prix derrière la connexion). |
| 16 à 21 : le reste | Les pages plus rares, une section du menu à la fois : les marchés, ce qui agit, ce qui est mesuré, ce qui est inventé, la machine, toi. |
| 22 : toutes les tailles | Chaque page juste du portable au grand écran ; sur le téléphone, des cartes qui s'ouvrent par le bas et des boutons LONG et SHORT assez grands pour le doigt. |
| 23 : les pages publiques | Le Mur, le Livre, la page investisseur et les emails (si tu dis oui). |
| 24 : le contrôle final | Le contrôle de l'étape 0 devient strict partout, au survol de la souris et sur téléphone compris : rien d'ancien ne peut revenir. Les pages d'erreur passent aussi au nouveau style. Exceptions notées : l'intro que tu gardes, l'admin Django, et les couleurs du mode clair s'il reste (jamais celles de l'argent). |

## Le calendrier, honnêtement

Environ 510 heures de travail en tout. Au rythme actuel (deux à trois livraisons d'affichage par semaine, à côté du travail sur l'argent, qui passe toujours en premier) :
- **le nouveau cadre sur toutes les pages : dans 1 à 2 semaines**, juste après les bandeaux qui défilent ;
- **tes pages principales** (ticket, positions, accueil, signaux, portefeuille, graphique) : **vers la sixième semaine** ;
- **plus rien d'ancien : environ trois mois** (une semaine de plus au pire).

## Ce qui ne change pas

- Tes ordres, tes stops, tes bots, les Orcs et les limites : aucune étape n'y touche.
- Les boutons gardent leurs mots, leurs étapes et ton PIN ; chaque confirmation reste là.
- Les chiffres restent les mêmes et se mettent à jour comme aujourd'hui ; un prix trop vieux reste montré comme vieux, une estimation le dit.
- La règle du rouge : le rouge plein veut dire argent réel, et seulement ça. Les rouges pleins qui la cassent encore aujourd'hui (la case du dernier prix sur le graphique, le bouton de fermeture sur la page d'une position, et le mode clair, où une baisse a exactement le rouge de REAL) disparaissent en route.
- Les bandeaux défilent en continu et s'arrêtent au survol.
- La magie reste : l'Œil, les titres en Orbitron, le menu en Rajdhani, les braises, ton choix Magie, Calme ou Éteint. L'animation d'intro reste exactement comme tu l'as voulue.

## Trois questions (une réponse courte suffit)

1. **Les pages publiques** (le Mur, le Livre, la page investisseur) : on les refait aussi, en dernier, sans changer ce qu'elles montrent ? Par défaut : oui. La fenêtre de connexion et de PIN du Mur, elle, est refaite dans tous les cas (étape 15) : c'est ta porte d'entrée.
2. **Le mode clair** (le bouton ☀ en haut, ou la touche t) : tu t'en sers ? Aujourd'hui, en mode clair, une baisse a exactement le même rouge que la pastille REAL. Par défaut on le garde, et une petite étape de plus y corrige les couleurs de l'argent ; si tu ne t'en sers jamais, on le retire.
3. **En haut** : un seul bandeau fin où les prix puis les news défilent côte à côte, ou deux bandeaux fins l'un sous l'autre ? Par défaut : un seul.

## Les images

Six images, l'ancien à gauche, la pièce du nouveau kit à droite, à la même échelle : 1. le cadre ; 2. les chiffres-clés ; 3. le tableau des positions ; 4. la fenêtre TAKE TRADE ; 5. les interrupteurs de la page Ops ; 6. le graphique.

*Données inventées, sur une copie locale : ce n'est pas ton compte.*
