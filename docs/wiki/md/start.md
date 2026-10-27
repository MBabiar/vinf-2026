# Vyhľadávač anime a mangy

Mário Babiar, Vyhľadávanie informácií 2026, FIIT STU

## O projekte

Vyhľadávač nad anime a mangou. Nájde dielo podľa názvu (aj alternatívneho), deja, žánru, roku, autora, štúdia alebo režiséra.
Odpovie aj na otázky, ktoré spájajú viac diel a ľudí: čo robilo štúdio v danom roku, kto adaptoval diela jedného autora, ktoré
mangy z časopisu dostali anime, od ktorej kapitoly mangy čítať po anime.

Na Anime News Network aj na MangaUpdates je každé dielo samostatná stránka a anime a manga sú na rôznych weboch. Google vráti
jednotlivé stránky, ale na otázku cez viac diel priamo neodpovie. Vyhľadávanie na ANN hľadá hlavne v názvoch.

## Zdroje

| Zdroj | Čo z neho beriem | Stiahnuté stránky |
| --- | --- | --- |
| [Anime News Network](https://www.animenewsnetwork.com/encyclopedia/), encyklopédia | anime a manga: názvy, typ, rok, žánre, dej, štáb a štúdiá (s ID osôb a firiem), vzťahy medzi dielami | 40 293 (13 826 anime, 26 467 manga), 4,8 GB |
| [MangaUpdates](https://www.mangaupdates.com/) | manga: autor, kresliar, časopis s kapitolami, vydavatelia, žánre, popis, kapitoly pokryté anime | 229 381 sérií + 2 534 strán katalógu, 30,9 GB |
| anglická Wikipédia (dump) | dlhší dej, demografia (shōnen, seinen…), kontrola štúdia a režiséra; spojenie cez šablónu s ANN ID | K3 |

**Dokument** = jedno dielo (anime alebo manga). Anime a mangu spájam cez „adapted from“ na ANN a zhodu názvu a autora s MangaUpdates.

## Ako to funguje

1. **Crawler** (vlastný, Python + `requests`): ide po číselných ID diel, dodržiava robots.txt a pauzy, každú stránku uloží ako
   jeden súbor HTML a každý request zapíše do TSV. Spolu 272 208 stránok, 35,7 GB HTML.
2. **Extraktor** (regex): z uložených stránok vytiahne polia diel do JSON: názvy, štáb, firmy, vzťahy, autori, časopisy
   (~8 M záznamov). Z nich vznikne 239 808 dokumentov; ANN a MU spojím podľa názvu a spoločnej osoby.
3. **Index** (vlastný TF index, skóre lnc.ltc, 2 metódy IDF) a vyhľadávanie z príkazového riadku.
4. **Spark**: spracovanie dumpu Wikipédie a spojenie s mojimi dátami.
5. **PyLucene**: nový index nad spojenými dátami.
6. **Vyhodnotenie**: porovnanie s očakávanými odpoveďami, Google a vyhľadávaním ANN.

## Príklady otázok

| Otázka | Odpoveď |
| --- | --- |
| Kto režíroval Cowboy Bebop a kedy sa vysielal? | Shinichirō Watanabe, od apríla 1998 |
| Ktoré anime robilo štúdio Madhouse v roku 2007? | Claymore, Den-noh Coil, Kaiji, Shigurui, Mokke, The Piano Forest… |
| Dopozeral som anime Claymore. Od ktorej kapitoly mangy čítať? | anime končí pri zv. 11, kap. 59 → od kap. 60 |

Všetkých 10 otázok je na stránke 1. konzultácie.

## Priebeh

| Míľnik | Termín | Stránka | Stav |
| --- | --- | --- | --- |
| 1. konzultácia: téma, zdroje, otázky | 30. 9. | [1. Konzultacia](https://vi2026.ui.sav.sk/doku.php?id=user:mario.babiar:1._konzultacia) | hotovo |
| 2. konzultácia (K2a): návrh crawlera | 14. 10. | [2. Konzultacia](https://vi2026.ui.sav.sk/doku.php?id=user:mario.babiar:2._konzultacia) | hotovo |
| 2. konzultácia (K2b): extraktor, index | 28. 10. | v [1. Odovzdanie](https://vi2026.ui.sav.sk/doku.php?id=user:mario.babiar:1._odovzdanie) | hotovo |
| 1. odovzdanie | 28. 10. | [1. Odovzdanie](https://vi2026.ui.sav.sk/doku.php?id=user:mario.babiar:1._odovzdanie) | hotovo |
| 3. konzultácia: Spark + Wikipédia | 11. 11. | 3. Konzultacia | |
| 4. konzultácia: PyLucene | 25. 11. | 4. Konzultacia | |
| 5. konzultácia: vyhodnotenie | 9. 12. | 5. Konzultacia | |
| 2. odovzdanie | 9. 12. | 2. Odovzdanie | |

**Technológie:** Python 3.14, `requests`, `re`, metadáta v TSV, dokumenty a index v JSON (bez databázy). Neskôr Spark
a PyLucene.
