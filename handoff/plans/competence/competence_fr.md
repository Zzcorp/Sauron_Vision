# Sauron sera-t-il compétent sur les marchés ?

## La réponse courte

Honnêtement : aujourd'hui, personne ne peut le dire, ni toi ni nous. Être compétent, c'est gagner en moyenne **après tous les frais**, sur des trades que la règle n'avait jamais vus, à une taille qui survit aux mauvaises séries. Sauron a de bons outils pour **limiter la casse** et pour **mesurer la vérité**. Il n'a pas encore montré qu'il **gagne** une fois tous les frais payés. Les notes du code de début octobre, qui résument tes messages de l'époque, disent que le départ n'a pas payé.

**Notre avis franc :** on ne parierait pas que toute la flotte gagne après frais. Le meilleur cas réaliste : une ou deux règles qui tiennent après les vrais frais d'eToro, en petite taille, et le reste en papier. S'il y arrive, ce sera par sa discipline (petite taille, juge sévère, mesure honnête), pas par ses idées de trade, qui sont publiques. Pour situer : selon le régulateur européen, 74 à 89 % des comptes CFD de particuliers perdent de l'argent, et en France l'AMF a compté 89 % de clients perdants sur quatre ans.

D'ici, on ne voit que le code, pas tes chiffres. Ce qu'on n'a pas pu confirmer est marqué **à vérifier**.

## Ce qui joue pour lui

- **Les bots misent petit par défaut :** 0,25 % de leur poche (pool) par trade, avec un stop tenu chez eToro. Par défaut, un bot cesse d'ouvrir après 4 pertes d'affilée ou 10 % de baisse de sa poche.
- **Un juge construit pour dire non :** le proving ground rejoue 14 règles comme le bot les trade, garde 30 % de l'historique de côté et double les frais. Depuis le 7 octobre, un bot ne met plus d'argent réel sur une règle FAILED.
- **Un filtre d'entrée qui connaît les frais eToro mesurés** (crypto 1 % par côté, actions 1 USD par côté) et refuse les trades qu'ils mangeraient.
- **Une mesure honnête :** tout est compté en R, et un résultat inconnu ne compte jamais pour zéro.
- **Une IA qui ne peut que freiner :** le Conseil et les Orcs observent sans toucher aux ordres. Le cerveau (le Mind) peut déjà mettre une règle en pause pour les bots, même sans avoir été noté, et le débat, une fois allumé, devient contraignant après 30 trades réels notés, quel que soit son score. Ces deux-là bloquent ou réduisent, sans jamais augmenter une taille.
- **Des garde-fous :** un kill switch protégé par le PIN (il désactive tous les bots, puis essaie de fermer les positions ; une fermeture qui échoue reste à faire à la main). Et pas d'entrée de bot au rollover, juste avant un week-end ou autour d'une grosse annonce.

Tout ça protège et mesure. Ça ne crée pas d'avantage. Et plusieurs protections ne marchent que si leur interrupteur est allumé : le juge de nuit, les gardes Morgul, le suivi des positions et Aragorn, le mode crise, la rétrogradation automatique des règles perdantes. Lesquels sont allumés chez toi : **à vérifier** (la commande le dira).

## Ce qui reste à prouver, et pourquoi

- **L'avantage lui-même.** Les idées de trade sont des techniques publiques (RSI, MACD, moyennes mobiles, Bollinger, ICT). Les études sont partagées : beaucoup trouvent des gains avant frais, mais les plus strictes les voient disparaître une fois les frais comptés. Début octobre, le code ne citait qu'une règle avec un avantage mesuré : bollinger_squeeze_breakout, +0,26R sur 43 signaux notés. Ce sont des signaux, pas des trades pris, et sans frais. Sur 43, la marge d'erreur est d'environ ±0,4R : ça peut encore être de la chance.
- **Le juge se trompe parfois.** Dans nos simulations, une règle sans aucun avantage sort PROVEN dans 1 à 5 % des cas. Il juge des dizaines de cas chaque nuit, chacun comme s'il était seul : quelques PROVEN peuvent donc être de la chance. PROVEN garde la pleine taille, et un vieux verdict ne périme jamais. Tout le reste sauf FAILED trade quand même en réel, à 0,25×, y compris les règles que le juge ne sait pas rejouer.
- **Les frais.** Le financement de nuit n'est compté que pour les ventes à découvert eToro mesurées en démo, depuis le 31 octobre, dans le filtre d'entrée : rien pour les achats, rien dans les résultats, rien en papier. Les frais eToro ne sont pas retirés des résultats, et le prix de sortie noté chez eToro est une estimation, pas le vrai prix d'exécution. Exemple, avec un taux d'illustration : en forex avec un stop à 0,3 %, une nuit à 6 % par an coûte environ 0,05R, donc deux nuits effacent un avantage de +0,1R. Les résultats des trades fermés et les portes de promotion sont donc plus beaux que la réalité.
- **Les échantillons.** Les promotions se décident sur 10 à 30 trades ou signaux. Exemple : une règle garde la pleine taille sur 20 signaux à +0,10R sans frais, ce qu'une règle sans avantage obtient une fois sur trois. Pour avoir 8 chances sur 10 de voir un petit avantage (+0,1R), il faut environ 1 200 trades ; avec 500 à 800, c'est une chance sur deux.
- **L'argent réel est arrivé avant la preuve.** Ton plan du 15 septembre prévoyait 2 à 3 mois de papier. Le 1er octobre, 36 règles sont passées en réel à la main, la plupart sans aucun signal noté : une promotion à la main ne passe aucun contrôle.
- **La taille.** Rien n'arrête le compte entier s'il baisse jour après jour : l'arrêt journalier ne regarde que les dernières 24 heures, et les autres freins sont par bot. Sur tes tickets manuels, au levier maximum par défaut, l'arrêt journalier, l'exposition totale et le verdict du juge ne sont que des avertissements. Le plafond est à 7 % de risque par trade : à ce niveau, 4 pertes d'affilée coûtent 25 %. Et un ticket manuel trop petit pour eToro est relevé au minimum d'eToro, jusqu'à ces 7 %.
- **Tes réglages, à vérifier.** Le code note un arrêt journalier mis à 8 % le 1er octobre (12 % pour les entrées « élite » ; défaut 3 %) et 100 % du compte engageable en marge depuis le 5 octobre (défaut 50 %). Ton risque réel par trade dépend de la poche et du réglage de chaque bot. Les plafonds choisis pour le futur Parieur iraient plus loin : deux pertes au plafond de 20 % coûtent 36 % du compte.
- **Les sorties à la main.** Sur la seule semaine analysée par le code (début octobre, papier et réel mélangés), 12 gagnants sur 15 ont été fermés à la main à +0,28R en moyenne, alors que les bots visent +2R. Si un gagnant rapporte +0,28R et qu'une perte coûte 1R, il faut gagner près de 8 trades sur 10 pour être à zéro (notre calcul).
- **Le coût de l'IA.** Environ 4 USD par jour début octobre, avant le Conseil et les Orcs (plafond par défaut : 15 USD par jour). Coût actuel **à vérifier**. Exemple : avec 2 000 USD et 0,25 % de risque, un avantage de +0,1R rapporte 0,50 USD par trade ; il faut alors 240 trades par mois pour payer 120 USD d'IA. À notre connaissance, aucune étude publiée ne montre qu'une IA de ce type donne un avantage durable.
- **Les mots qui trompent.** Dans les commandes et chez Aragorn, « live » mélange compte réel et compte démo. « Paid » s'affiche dès que la moyenne est positive, même sur un seul trade. Le « Profit factor » de /command/ est en fait le gain moyen divisé par la perte moyenne.

## Ce qui ferait la différence

1. **Compter les vrais frais partout** (financement de nuit, frais eToro, vrai prix de sortie) : dans les résultats, le papier et le proving ground. Ton « plus tard » pour les vrais frais doit devenir « maintenant ».
2. **Rester petit tant que la preuve n'est pas là :** 0,25 à 0,5 % de risque par trade, un levier plafonné pour les bots, les tickets manuels sous les mêmes limites dures que les bots, et un arrêt dur si le compte entier baisse trop depuis son plus haut.
3. **Une seule porte vers l'argent réel :** PROVEN aux vrais frais, même pour une promotion faite à la main. Le reste en papier, pas à 0,25×.
4. **Moins de règles, mais meilleures**, et laisser les sorties travailler.
5. **Un bulletin de compétence :** réel seulement, net de frais, avec une marge d'erreur, mois par mois.

## La commande pour qu'on regarde tes vrais chiffres

Elle ne fait que lire, et n'affiche aucun montant d'argent : seulement des R, des pourcentages, des nombres de trades, des noms de règles et de symboles. On l'a testée sur une copie d'essai, pas sur ton serveur. Colle tout le bloc d'un coup dans le terminal du serveur :

```
cd ~/Sauron_Vision
sh -c 'for c in "component list" \
  "scorecard --days 3650 --venue live --by lane" \
  "scorecard --days 3650 --venue live --by rule" \
  "scorecard --days 3650 --venue live --by exit" \
  "scorecard --days 3650 --venue paper --by rule" \
  "side_scorecard" "prove show" "bar_losers"
do echo "=== $c"; ./deploy/dc exec -T web python manage.py $c; done' > ~/competence.txt 2>&1
```

Rien ne s'affiche pendant qu'elle tourne : attends que le terminal rende la main. Puis affiche le fichier et colle-nous le texte :

```
cat ~/competence.txt
```

On y verra quels interrupteurs sont allumés, quelles règles portent le résultat et lesquelles perdent. Deux limites : « live » y mélange réel et démo, et tous les R sont avant frais. Pour un verdict sur l'argent réel seul, il faudra un deuxième petit script de lecture, testé de la même façon, qu'on t'enverra. Évite aussi le dimanche : ce jour-là, `prove show` affiche le générateur, pas le verdict de tes règles.

Et un contrôle que toi seul peux faire : dans ton relevé eToro des 3 derniers mois, regarde le total des frais de nuit (overnight) et des autres frais. C'est ce que Sauron ne retire pas de ses résultats.

Les chiffres des régulateurs et des études viennent de résumés de recherche : on n'a pas pu ouvrir les pages d'origine d'ici.
