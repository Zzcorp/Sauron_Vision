# Anduin : la page des flux

Proposition du 12 novembre 2026, deuxième version après relecture. Rien n'est construit ; la maquette tourne sur des données inventées.

**Ce que tu reçois :** deux vidéos de 13 secondes (la maquette, puis la même histoire au rythme réel des prix d'aujourd'hui), quatre images (la page au repos, un livre de quarante positions, les trois météos, le téléphone) et la planche 7 de l'aperçu.

## Le nom

**Anduin**, le Grand Fleuve. Adresse /anduin/, ouverte depuis la barre latérale, et depuis Barad-dûr dès qu'elle existe. L'Operations Center reste ton bureau.

## Ce que tu verras

- **Un fleuve, de gauche à droite :** l'amont à gauche (prix et signaux), l'aval à droite (clôtures).
- **Cinq paniers,** un par famille : Forex, Crypto, Commodities, Stocks & ETFs, Indices. Le panier au trait plein, c'est l'argent réel seul : il grossit avec le volume REAL qu'il porte ; vide, il n'est qu'une fente en pointillé.
- **DEMO, PAPER et « no venue » sont rangés à part,** dans une annexe en pointillé, sous le panier ou à côté. Chaque monde a sa bande, sa somme et sa barre. Rien n'additionne deux mondes : ni un chiffre, ni une forme.
- **Les positions sont des blocs,** hauts selon leur taille, sur une seule échelle que l'argent réel fixe : pleine hauteur = ta plus grosse position REAL. L'échelle est écrite en bas de page (« full height = $21,749.00 »). Un bloc DEMO ou PAPER plus gros est plafonné et marqué « › ».
- **Chaque bloc dit son pari :** symbole, LONG ou SHORT, R actuel, âge de son prix. S'il est assez haut, il ajoute le risque au stop, le stop et la cible (SL, TP), et son origine (ton ticket et son signal, ou telle règle de tel bot ; le numéro du signal d'un bot n'est pas enregistré aujourd'hui). Pour un petit bloc, le reste est au survol et dans le tableau. Une barre au pied de chaque bloc redit sa taille.
- **En bas :** RESERVE (le disponible et l'utilisé d'eToro, avec leur âge, pour le monde où ton compte est branché ; l'autre affiche un tiret ; l'utilisé se partage entre « on Sauron » et « outside »), UPSTREAM · 24 H (signaux arrivés et pris sur 24 h ; pour les refus, le dernier motif connu de chaque symbole, bot par bot), DOWNSTREAM · 24 H (les clôtures en R).
- **Combien de positions tiennent :** sur un livre d'essai de 40 positions, un écran de 1440 × 900 en dessine 21 (les 7 REAL en blocs entiers, les autres en blocs ou en lignes) et replie le reste sous « +N more · in the table ». Un écran de 1920 × 1080 dessine les 40. L'argent réel se replie en dernier.

## Ce qui bouge, et pourquoi

Rien ne bouge sans une vraie donnée derrière, et la page ne demande rien à l'écran quand rien ne bouge.

- **Un point vert = un prix qui arrive.** Il entre dans le fleuve à la porte de son panier et rejoint son bloc en une seconde environ. L'âge affiché vient de l'heure du prix, jamais de l'animation. Passé 15 minutes sans prix, le filet s'assèche : trait ambre en pointillé, et le ⚠ de la Horde.
- **Un losange = un signal.** Pris, il entre dans son panier et un bloc se forme. Refusé, il s'évapore à l'entrée, et une étiquette dit quel bot, dans quel monde, et le code de `why_no_trade` : « XAGUSD refused by Commodities #4 REAL · cost_filter ». Le détail enregistré par le bot s'écrit mot pour mot dans UPSTREAM.
- **Attendre n'est pas refuser.** Un bot qui vote non, qui tient déjà le symbole ou qui vient d'en sortir est compté à part (« waiting »), sans losange.
- **Des petits carrés blancs = l'argent d'un ordre.** Ils partent de la réserve à l'ouverture et y reviennent à la clôture. Le résultat se lit sur le chiffre : jade pour un gain, corail pour une perte, et seulement pour l'argent réel soldé au prix d'eToro ; DEMO, PAPER et estimations restent en blanc.
- **La maquette condense.** La seconde vidéo montre le rythme réel d'aujourd'hui : un prix eToro toutes les 30 secondes au mieux, donc un fleuve calme.

## La météo du marché

- **Le niveau de stress** que les bots suivent déjà (calm, stressed, crisis, recovery), avec son score et son âge. Plus il monte, plus le courant est rapide, plus les trois lignes du fleuve sont hautes, et le contour des paniers vire à l'ambre, puis au corail. Si l'interrupteur crisis_mode est éteint, la page écrit « not measured » et le fleuve reste plat.
- **La volatilité de chaque famille** rehausse le fleuve dans son panier.
- **Un marché fermé gèle son panier** (forex, actions, matières premières) : givre, plus aucun point, « shut · reopens 14:30 UTC ». Les indices ne gèlent pas : leur CFD se négocie presque sans arrêt.
- **Une grosse annonce approche comme un front,** sur une frise de 6 heures. Dans l'heure qui précède, une bande hachurée ambre court au-dessus des paniers touchés, et leurs blocs portent le ⚠ de la Horde.

## Ce qu'elle ne fait pas

- **Aucun bouton d'argent :** CLOSE et TAKE TRADE restent sur leurs pages.
- **Aucun appel à eToro ni à un modèle, aucun faux chiffre.** Un chiffre absent est un tiret qui dit pourquoi.
- **Elle s'arrête** onglet caché, sous le verrou, ou si ton système demande moins d'animations ; « Read as a table » donne tout en tableau.
- **Coût,** mesuré sur la maquette, sur une machine sans carte graphique : au repos complet, celui d'une page immobile ; un dixième de cœur au rythme réel des prix ; un tiers de cœur au plus fort de l'histoire.

## Sur téléphone

Pas de fleuve ni de particules : la météo, la réserve (REAL d'abord), les paniers et leurs blocs en liste, puis « Last events », les cinq derniers faits que le fleuve aurait montrés.

## Les étapes

| Étape | Ce que tu auras | Quand |
|---|---|---|
| A1 | La vraie page sur tes données, en lecture seule ; les flux sont relevés toutes les 10 à 30 secondes | Après S1a et la magie |
| A2 | Les flux à l'instant même de l'ordre ou du signal | Après A1 |
| A3 | La volatilité par famille ; « les dernières 24 h » rejouées | Après A2 |

Aucune étape ne touche à un ordre, à une taille ou à un interrupteur.

## Les OK dont on a besoin

1. **Le nom** « Anduin », ou le tien.
2. **Les paniers par famille** par défaut (monde, bot ou thème à un clic).
3. **Les blocs selon l'exposition** (ton « selon volumes »), ou selon le risque au stop, qui étale mieux les hauteurs quand une position écrase les autres ?
4. **Une page à elle,** ouverte depuis la barre latérale, puis depuis Barad-dûr.
5. **La météo présente comme dans la maquette.** Ou plus discrète, ou plus forte ?
6. **L'échelle.** Proposé : l'argent réel fixe l'échelle et la taille des paniers ; DEMO et PAPER sont rangés à part dans chaque panier. Sinon : une seule échelle, où un gros bloc DEMO ou PAPER écrase tes blocs REAL.

Si les choix proposés te vont, « 6 okay » suffit.
