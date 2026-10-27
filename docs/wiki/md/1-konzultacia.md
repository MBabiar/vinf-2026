# Vyhľadávač anime a mangy

## TL;DR

Chcem spraviť vyhľadávač nad anime a mangou. Chcel by som, aby našiel dielo podľa názvu (aj alternatívneho), deja, žánru, roku, autora, štúdia alebo režiséra a vedel odpovedať aj na otázky, ktoré spájajú viac diel a ľudí, napríklad čo robilo štúdio v danom roku, kto adaptoval diela jedného autora, ktoré mangy z časopisu dostali anime. Anime plánujem stiahnuť z encyklopédie Anime News Network (ANN), mangu z MangaUpdates. Ak sa podarí anime a mangu prepojiť, vyhľadávač by mohol povedať aj to, z ktorej mangy anime vzniklo a kde v mange anime končí. Z anglickej Wikipédie chcem doplniť dlhší opis deja a demografiu pri anime; štúdio a režisér z jej infoboxu by sa mohli hodiť pri vyhodnotení.

## Motivácia

Otázky fanúšikov bývajú jednoduché („kto režíroval Cowboy Bebop“, „anime o lovcovi odmien, ktorý lieta z planéty na planétu“) aj zložitejšie („čo všetko robilo Madhouse v roku 2007“, „ktorí režiséri adaptovali viac diel Rumiko Takahashi“, „od ktorej kapitoly mangy čítať po anime“). Na ANN aj na MangaUpdates je každé dielo samostatná stránka (vyhľadávanie na ANN hľadá hlavne v názvoch) a anime a manga sú na rôznych weboch, takže štáb anime sa nedá spojiť s údajmi o mange. Google vráti jednotlivé stránky, ale na otázky, ktoré spájajú viac diel a ľudí, priamo neodpovie.

Každý zdroj má inú úlohu: ANN je databáza anime (štáb, štúdiá, vzťahy medzi dielami cez ID), MangaUpdates je databáza mangy (autor, časopis, vydavateľ, demografia, kapitoly pokryté anime). Odpovede by mali pochádzať hlavne z týchto dvoch stránok, Wikipédia ich iba dopĺňa.

## Stránky na scrapovanie

### 1. Anime News Network – anime

[Claymore (TV)](https://www.animenewsnetwork.com/encyclopedia/anime.php?id=7028), [Cowboy Bebop (TV)](https://www.animenewsnetwork.com/encyclopedia/anime.php?id=13). robots.txt stránky diel povoľuje (zakazuje napr. vyhľadávanie a `&lookup=`), `Crawl-delay: 2` (pauzu plánujem 3–5 s); ochranu proti botom som nevidel. V encyklopédii je odhadom okolo 12 000 anime.

Na stránkach, ktoré som prezeral, sú polia v HTML označené rovnako (`<div id="infotype-N"><strong>Názov poľa:</strong>`, štáb v bloku `data-encyc-credits="JP staff"`):

| Pole | Príklad (Claymore, TV) | Poznámka |
| --- | --- | --- |
| názov, alternatívne názvy | Claymore; Клеймор, クレイモア | neanglické názvy chcem držať iba v poli názvov, nie v texte |
| typ, počet epizód | TV, 26 | TV, film, OVA, special |
| vysielanie (Vintage) | 2007-04-03 to 2007-09-25 | rok na filter |
| žánre, témy | action, drama, fantasy, romance; female warriors, medieval, swordplay… | |
| dej (Plot Summary) | krátky opis | často iba pár viet, doplní ho Wikipédia |
| predloha (adapted from) | Claymore (manga), odkaz `manga.php?id=…` | podľa neho chcem spojiť anime s mangou |
| súvisiace diela | sequel, prequel, spinoff, remake, compilation… | typ vzťahu + ID diela |
| štáb (rola: osoba s ID) | Director: Hiroyuki Tanaka; Series Composition: Yasuko Kobayashi | veľa rôznych názvov rolí (Director, Series Director…) |
| firmy (rola: firma s ID) | Animation Production: Madhouse | hlavné štúdio nie je vždy jasné, rola sa volá rôzne |
| dabing (herec s ID – postava) | | japonský aj anglický |

### 2. MangaUpdates – manga

[Claymore](https://www.mangaupdates.com/series/xti92gy/claymore). robots.txt povoľuje stránky sérií pre bežné crawlery (`User-agent: *`), zakazuje napr. vyhľadávanie a komentáre; bez Crawl-delay (pauzu plánujem 3–5 s); ochranu proti botom som nevidel. Séria má číselné ID (asi 200 000). Stránky, ktoré som prezeral, majú jednu šablónu, každé pole má atribút `data-cy="info-box-<pole>"`.

| Pole | Príklad (Claymore) |
| --- | --- |
| názov, pridružené názvy | Claymore; Kureimoa, クレイモア, 大剑… |
| typ | Manga (aj Manhwa, Manhua; doujinshi asi vyradím) |
| popis | krátky opis deja |
| autor, kresliar (s ID) | YAGI Norihiro |
| rok | 2001 |
| stav | 27 zväzkov (Complete) |
| **Anime Start/End Chapter** | Starts at Vol 1, Chap 1; Ends at Vol 11, Chap 59 (Original Ending EP 24-26) |
| časopis (Serialized In) | Gekkan Shounen Jump (Chap 1–73), Jump SQ (Chap 74–155) |
| pôvodný a anglický vydavateľ | Shueisha; Viz (27 zväzkov) |
| žánre (aj demografia), kategórie (tagy) | Action, Fantasy, Horror, **Shounen**…; Female Fighter/s, Sword/s, Time Skip… |
| súvisiace série | Adapted From, Sequel, Side Story, Spin-Off… |

Dokument, ktorý vyhľadávač vráti, by bol **jedno dielo** (anime alebo manga, 1 stránka = 1 súbor) s poľami z tabuliek; ak sa manga a anime spoja, budú na seba odkazovať. Plánované tabuľky (TSV): diela, názvy, vzťahy, štáb, firmy, dabing, mangy, kapitoly pokryté anime.

**Spojenie ANN ↔ MangaUpdates:** stránky na seba neodkazujú. Anime na ANN má predlohu „adapted from … (manga)“ s názvom mangy a ten by som hľadal medzi názvami a pridruženými názvami v MangaUpdates. Zhodu chcem kontrolovať autorom (rovnaký autor na oboch stránkach), lebo podľa samotného názvu sa môže spojiť aj iná séria.

## Wikipédia

- **Články o mangách a anime**, napr. [Claymore (manga)](https://en.wikipedia.org/wiki/Claymore_(manga)): demografia (shōnen, seinen…), časopis, dlhší opis deja, štúdio a režisér v infoboxe.
- **Články o ľuďoch**, napr. [Rumiko Takahashi](https://en.wikipedia.org/wiki/Rumiko_Takahashi): narodenie, ocenenia.

Spojenie: články majú v externých odkazoch šablónu s presným ANN ID (`{{Anime News Network|anime|46}}`), takže by sa mali dať spojiť cez ID, nie podľa názvu. Pri článkoch o ľuďoch to vyzerá podobne.

Z Wikipédie chcem hlavne dlhší opis deja (na ANN býva krátky) a demografiu pri anime (shōnen, seinen…). Štúdio a režisér z infoboxu by sa dali použiť aj na kontrolu, či ich z ANN vyťahujem správne.

## Otázky a odpovede

| Otázka | Odpoveď | Zdroj |
| --- | --- | --- |
| Kto režíroval Cowboy Bebop a kedy sa vysielal? | Shinichirō Watanabe (na ANN rola „Series Director“), od apríla 1998 | ANN |
| Aké anime je o lovcovi odmien s temnou minulosťou, ktorý s partiou lieta z planéty na planétu? (hľadanie podľa deja) | Cowboy Bebop (dej na ANN: „Spike Spiegel, a bounty hunter with a dark past… from planet to planet“) | ANN |
| Ktoré anime robilo štúdio Madhouse v roku 2007? | napr. Claymore, Den-noh Coil, Kaiji: Ultimate Survivor, Shigurui, Mokke, The Piano Forest | ANN |
| Kto nakreslil mangu Claymore a kde vychádzala? | Norihiro Yagi; Gekkan Shōnen Jump (kap. 1–73), potom Jump SQ; v angličtine Viz | MangaUpdates |
| Dopozeral som anime Claymore (2007). Od ktorej kapitoly mangy mám čítať? | anime končí pri zv. 11, kap. 59, čítať od kap. 60 (epizódy 24–26 majú vlastný koniec, niektoré kapitoly vynecháva); seriál robilo Madhouse, režisér Hiroyuki Tanaka | MangaUpdates + ANN |
| Aké anime adaptácie má Berserk, v akom poradí, ktoré štúdio ich robilo a kde v mange končia? | 1997 TV (OLM, končí zv. 13, kap. 87), 2012–2013 tri filmy Golden Age Arc (Studio 4°C, zv. 13, kap. 91), 2016–2017 TV (GEMBA, Millepensee, zv. 29, kap. 249), 2022 Memorial Edition (Studio 4°C) | ANN + MangaUpdates |
| Ktorí režiséri robili anime podľa viacerých diel Rumiko Takahashi? | Motosuke Takahashi (Fire Tripper, Maris the Chojo, The Laughing Target), Kazuo Yamazaki (Urusei Yatsura, Maison Ikkoku), Tomomi Mochizuki (Maison Ikkoku, Ranma ½) | ANN |
| Ktoré mangy z časopisu Afternoon (Kodansha) majú anime a kde anime končí? | napr. Kiseijuu (zv. 10, kap. 64), Shion no Ou (zv. 8, kap. 50), Narutaru (zv. 6, kap. 29), Mushishi (1. sezóna zv. 6, kap. 26; 2. sezóna zv. 10, kap. 50) | MangaUpdates |
| Ktoré mangy dostali po rokoch nový seriál od iného štúdia? | napr. Fruits Basket (2001 Studio DEEN, 2019 TMS/8PAN), Hunter × Hunter (1999 Nippon Animation, 2011 Madhouse) | ANN |
| Ktoré seinen mangy mali anime od viacerých štúdií? | napr. Berserk (seinen podľa MangaUpdates, overené Wikipédiou; OLM, Studio 4°C, GEMBA/Millepensee podľa ANN) | ANN + MangaUpdates (+ Wikipédia) |
