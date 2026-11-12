# Réel, démo et papier séparés : le plan (3e version)

Tu as dit oui à deux choses.
1. Les limites qui protègent ton argent réel ne comptent plus que l'argent réel. La démo sort du risque compté et de la taille du compte que les limites utilisent.
2. Sur le ticket, tu choisis eToro REAL ou eToro DEMO, côte à côte. Pour un ticket REAL, ton PIN est demandé une deuxième fois.

## Déjà fait par d'autres chantiers (retiré de ce plan)
- **Centre d'opérations (OC0, en cours).** Les lignes démo n'y sont plus marquées REAL MONEY, les mondes n'y sont plus additionnés, et le voyant « armé » ne compte que les bots sur un compte réel.
- **Oculus (O0, fusionné).** Sa colonne REAL ne compte que le réel.
- **#89 (fusionné).** Les positions eToro ouvertes montrent le P&L calculé par eToro lui-même.

## Ce qui change, étape par étape
1. **W0 · Une seule règle** pour dire si une ligne est réelle, démo ou papier. Pour toi, presque rien ne change. Seul détail : sur /command/ et /eye/, une clôture sans prix de sortie s'affiche « non mesurée » au lieu de 0,00.
2. **C1 · La Horde en onglets.** Il y a un onglet par monde : REAL, DEMO et PAPER, plus HAND s'il existe une position tenue à la main sans courtier. Chaque onglet a ses propres chiffres, qui ne sont jamais additionnés.
   - La case AT ETORO s'affiche sur l'onglet de son monde.
   - Dans le bandeau du bas, OPEN P&L et REALISED 24H montrent l'argent réel, avec la démo et le papier à côté.
   - La fenêtre de clôture d'une position démo dit DEMO. Aujourd'hui elle dit LIVE.
   - C'est de l'affichage seulement.
3. **C2 · « Results by World ».** L'ancienne page « Bot Equity Curve » prend ce nom. On choisit un monde, puis Courbes, P&L ou Stats. Affichage seulement.
4. **C3 · Le compte sur le ticket.** Tu choisis PAPER ou le courtier dans le monde où est réglée la case Demo. Par défaut, le ticket fait ce qu'il fait aujourd'hui. Cette étape ajoute des refus, tous avant que quoi que ce soit parte. Sauron ne te propose jamais un compte où plus d'argent réel est en jeu.
5. **L · Les limites sur l'argent réel seul, d'abord en ombre.**
   - Chaque entrée est jugée deux fois. La façon d'aujourd'hui décide ; la nouvelle est seulement enregistrée.
   - Un nouvel interrupteur, `real_only_limits_live`, arrive éteint. Il ne s'allume qu'avec ton PIN, et le bouton « all on » ne l'allume jamais.
   - Après au moins 14 jours, tu lis la liste de ce qui aurait été autorisé en plus, avec ce que ces trades auraient rapporté ou coûté, puis tu l'allumes.
   - Pour revenir à aujourd'hui, tu l'éteins ; il ne faut pas de PIN pour ça.
6. **C4 · eToro REAL et DEMO côte à côte.**
   - **C4a.** Sauron lit les deux mondes séparément. Les positions démo restées ouvertes après avoir décoché Demo redeviennent gérables et fermables.
   - **C4b.** Deux voies pour tes trades à la main : la voie REAL (ta voie actuelle) et une nouvelle voie DEMO. Chacune s'arme avec ton PIN. La voie REAL demande en plus une deuxième confirmation et une lecture fraîche de ton compte réel. Tout tourne d'abord en ombre.
   - **C4c.** Le ticket propose les deux voies. Un ticket REAL finit sur un panneau « REAL MONEY » qui montre l'ordre exact, et tu y retapes ton PIN avant l'envoi.
   - Ce deuxième interrupteur ne peut pas s'allumer tant que L est éteint.
7. **C5 · Les derniers filtres par monde.** /positions/, /portfolio/, l'historique des exécutions et la trésorerie. Affichage seulement.

## Quand tu allumes L : plus souple pour l'argent réel
- Les positions démo ne prennent plus de place dans tes limites réelles : risque ouvert max, exposition totale et plafond de notionnel.
- Une perte démo ne compte plus dans ta perte du jour réelle. Le stop du jour, le mode « élite » et l'arrêt absolu se déclenchent donc plus tard.
- Une perte démo ne divise plus par deux la taille de tes entrées réelles (le mode élite). Dans ce cas, tes entrées réelles sont donc plus grosses qu'aujourd'hui.
- Une position démo ne bloque plus une entrée réelle sur la même idée et ne compte plus dans les thèmes de devises. Elle ne réduit plus non plus la taille d'une entrée réelle à cause de la corrélation, donc cette entrée peut être plus grosse.
- Les positions démo restées ouvertes après avoir décoché Demo ne bloquent plus rien côté réel. Aujourd'hui, c'est l'effet le plus visible.
- Les places d'un bot et sa perte du jour ne comptent plus les lignes de l'autre monde.
- Le bureau de capital, s'il est en mode live, ne compte plus la démo dans son risque.
- Sur ton ticket, tu as moins d'avertissements, et une position démo ne déclenche plus le refus « position non montrée ».
- Quand ta lecture eToro a plus de 2 h, les limites se mesurent contre une taille de compte de secours. Cette taille ne contient plus le P&L papier, ce qui est plus souple tant que le papier perd.
- Quand la case Demo est cochée, tes limites réelles ne se mesurent plus contre la taille du compte démo, mais contre ta taille réelle. C'est plus souple si le compte démo est plus petit. Aujourd'hui, aucun ordre réel eToro ne peut partir dans ce cas.

## Quand tu allumes L : plus strict pour l'argent réel
- Un gain démo ne compense plus une perte réelle. Le stop du jour se déclenche donc plus tôt sur une perte réelle.
- Une ancienne ligne du livre « Main » n'est plus ignorée quand seule une position démo tenait son symbole.
- La taille de secours ne contient plus le notionnel démo, ni le P&L papier tant que le papier gagne.
- Le budget « live » du bureau de capital ne compte plus le capital des bots qui tradent en démo.
- Sur ton ticket, l'avertissement de perte du jour arrive plus tôt.

La démo devient un monde à part. Elle a les mêmes pourcentages que le réel, mesurés sur son propre compte démo.

## Quand tu allumes C4
- **Plus souple.**
  - Tu peux passer un ticket REAL pendant que les bots tradent en démo, ce qui est impossible aujourd'hui.
  - Tu peux passer un ticket DEMO pendant que les bots tradent en réel.
  - La trésorerie est comptée par monde : un ordre démo n'est jamais déduit de ta trésorerie réelle.
  - La voie REAL suit ton compte réel. Avec la case Demo cochée, elle ne suit plus le compte démo.
- **Plus strict.**
  - Le PIN est demandé deux fois pour REAL.
  - L'armement de la voie REAL demande le PIN, une deuxième confirmation et une lecture fraîche de ton compte réel.
  - Chaque ordre est jugé sur la trésorerie de son propre monde.
  - Les ordres démo ne peuvent plus prendre la place des ordres réels dans le quota de requêtes eToro.
  - Cocher Demo est refusé tant que la voie REAL tient une position réelle.
- **Les bots ne changent pas.** Ils suivent la case Demo, comme aujourd'hui.

## L'ordre
1. W0, dès que OC0 est fusionné.
2. C1 et L (L1 puis L2) en parallèle. L démarre tôt parce que son ombre doit tourner au moins 14 jours.
3. C2 et C3. C4a peut commencer en même temps que C3.
4. Tu allumes L, après l'ombre et ta lecture de la liste.
5. C4b, puis C4c. Ensuite tu allumes C4.
6. C5, à tout moment après C1.

## Ce qu'il te reste à décider
1. **D3.** Quand les deux mondes existent, sur quel monde tradent les bots ? Je propose que la case Demo continue de décider pour eux, comme aujourd'hui.
2. **Le deuxième PIN.** Je l'ai compris comme « le PIN deux fois, en deux étapes, la deuxième sur un panneau REAL MONEY qui montre l'ordre exact ». Si tu voulais autre chose, par exemple une case à cocher, dis-le.
3. **Des limites pour la démo.** Je propose qu'elle ait ses propres limites (mêmes pourcentages, mesurés sur son compte démo), pour qu'elle se comporte comme le réel. L'autre choix est une démo sans limite propre. Les deux ne changent rien pour l'argent réel.
4. **D6 (nouveau, séparé).** Le bureau de capital, les notes des règles et les plans de parts comptent encore les trades démo fermés comme une preuve « live ». Cela influence les tailles réelles. Je propose de le traiter après L, avec sa propre ombre.
5. **D5 (inchangé).** Faut-il refuser sur ton ticket les courtiers qui n'ont pas encore de preuve d'exécution (Saxo, OANDA, Alpaca, Binance en réel) ?
6. **Quand allumer L.** Après 14 jours d'ombre et ta lecture de la liste « plus souple ».
