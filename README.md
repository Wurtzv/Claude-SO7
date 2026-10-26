# Indbrudskort Jylland

Et kort over anmeldte indbrud i Jylland, bygget på de jyske politikredses offentlige døgnrapporter.
Et Python-script henter de nye rapporter hver morgen, trækker vej, by, gerningstid og type ud,
finder vejens midtpunkt og gemmer det hele i `data/indbrud.json`. En statisk side med Leaflet og
OpenStreetMap viser indbruddene på et kort, og den bliver lagt på GitHub Pages.

## Indhold

| Sti | Hvad |
|---|---|
| `indbrudskort/parse.py` | Listeformatet (Østjylland): finder listen over indbrud og tolker hver linje |
| `indbrudskort/afsnit.py` | Afsnitsformatet (Nordjylland, enkeltsager på Ritzau): "Indbrud i villa" + brødtekst |
| `indbrudskort/kilder.py` | Kilderne: politi.dk-døgnrapporter og Via Ritzau. **Nye kredse og kilder tilføjes her** |
| `indbrudskort/geokod.py` | Vej + by → koordinat midt på vejen, med cache |
| `indbrudskort/lager.py` | `data/indbrud.json`: fletning uden dubletter |
| `indbrudskort/naboer.py` | Naboveje: vejene inden for ca. 500 m af hvert indbrud fra de seneste 30 dage → `data/naboveje.json` |
| `indbrudskort/ugerapport.py` | Ugens opsummering (seneste 7 dage mod de 7 før) → `data/ugerapport.json` (vises på kortsiden) |
| `indbrudskort/statistik.py` | Anmeldte indbrud pr. jysk kommune pr. kvartal fra Danmarks Statistik → `data/statistik.json` |
| `data/indbrud.json` | Alle indbrud (bliver opdateret automatisk) |
| `data/geokode-cache.json` | Cache over geokodede veje og byer |
| `data/startdata.json` | De 31 indbrud fra prototypen (17.–22. okt. 2026), som blev brugt som startdata |
| `site/` | Kortsiden (`index.html`, `app.js`, `style.css`) |
| `tests/` | Tests med gemte rapporter i `tests/fixtures/` |
| `.github/workflows/opdater.yml` | Kørsel fire gange dagligt (06:17, 10:17, 13:17 og 17:17 UTC), commit af nye data og udgivelse på GitHub Pages |
| `.github/workflows/test.yml` | Tests og en prøvekørsel mod de rigtige kilder ved hvert push til en gren |

## Kom i gang lokalt

Det kræver Python 3.10 eller nyere. Selve scriptet bruger kun standardbiblioteket, og `pytest` skal kun bruges til testene.

```bash
pip install pytest
python -m pytest                          # kør testene
python -m indbrudskort opdater            # hent de seneste 14 dages rapporter og geokod dem
python -m indbrudskort opdater --dage 30  # kig længere tilbage
python -m indbrudskort opdater --prøvekørsel --uden-geokodning   # hent og parse, men gem intet
```

Sådan ser du kortet lokalt:

```bash
python -m http.server 8000
# åbn http://localhost:8000/site/  (siden henter ../data/indbrud.json, når den kører lokalt)
```

## Opsætning på GitHub

1. **Slå GitHub Pages til:** Gå til *Settings → Pages → Build and deployment → Source* og vælg **GitHub Actions**.
2. **Giv Actions lov til at skrive:** Gå til *Settings → Actions → General → Workflow permissions* og vælg **Read and write permissions**, så workflowet kan committe nye data.
3. **Valgfrit: Dansk adresse-API.** Opret en gratis bruger på Dataforsyningen og lav en token. Læg den som repository-secret med navnet `DATAFORSYNINGEN_TOKEN` under *Settings → Secrets and variables → Actions*. Uden token bruges kun Nominatim.
4. Kør workflowet **Opdater indbrudskort** én gang manuelt (*Actions → Opdater indbrudskort → Run workflow*). Bagefter kører det selv fire gange om dagen, så døgnrapporter, der udgives midt på dagen, hurtigt kommer på kortet. Nye rapporter kan også hentes med det samme med *Run workflow*. Det kører også ved push til `main`, når kode, side eller startdata ændres.

Workflowet kører først testene. Hvis politiet ændrer formatet, så parseren går i stykker, bliver kørslen rød i stedet for at gemme forkerte data. Kørslen fejler også, hvis ingen af kilderne kan nås.

## Sådan virker det

### Kilder og politikredse

| Politikreds | Hvor | Format | Hvad kommer med |
|---|---|---|---|
| Østjyllands Politi | politi.dk + Via Ritzau (90721) | Fast liste "anmeldt … indbrud i privat beboelse" | Alle anmeldte indbrud i privat beboelse, med vej og bydel |
| Nordjyllands Politi | politi.dk | Nyhedsafsnit "Indbrud i …" | Udvalgte indbrud (privat og erhverv), med by/bydel og ugedag – sjældent vej |
| Sydøstjyllands Politi | Via Ritzau (90720) | Enkeltsager | Kun meddelelser, hvis titel begynder med "Indbrud" |
| Midt- og Vestjyllands Politi | Via Ritzau (90687) | Enkeltsager | Som ovenfor |
| Syd- og Sønderjyllands Politi | Via Ritzau (90686) | Enkeltsager | Som ovenfor |

Midt- og Vestjylland, Sydøstjylland og Syd- og Sønderjylland lægger (oktober 2026) ingen døgnrapporter på politi.dk, og deres Ritzau-meddelelser handler næsten aldrig om indbrud. Kortet er derfor langt mere komplet for Øst- og Nordjylland. Begynder en af kredsene at udgive døgnrapporter, tilføjes den som beskrevet nederst.

- **politi.dk:** Oversigten `https://politi.dk/doegnrapporter?district=OEstjyllands-Politi` (og `Nordjyllands-Politi`) har listen over rapporter som JSON inde i HTML'en (felterne `Link`, `ListDate` og `Headline`), så scriptet behøver ikke køre JavaScript. I hver rapport står indbruddene efter sætningen *"Der er det seneste døgn anmeldt … indbrud i privat beboelse"*.
- **Via Ritzau:** `https://via.ritzau.dk/json/v2/releases?publisher=90721` giver Østjyllands Politis pressemeddelelser med brødtekst. Her ligger "Døgnets indbrud i privat beboelse", og det er også her, døgnrapporten bliver lagt, når politi.dk har tekniske problemer.

Meddelelser, der er behandlet én gang, bliver husket i `behandlede_meddelelser` i `data/indbrud.json` og hentes ikke igen. Brug `--alle` for at genbehandle dem.

### Parseren

Formatet varierer en del, og testene dækker bl.a.:

- `På Klintevej i Hammel begået mellem onsdag d. 14/10 og søndag d. 18/10`
- `Sehierupsvej i Højbjerg mellem d. 12/10 kl. 10.00 til d. 16/10 kl. 08.15`
- `På Farøvænget i Tilst begået den 10/10 mellem kl. 10:45 og den kl. 17:07.`
- `Sletterhagevej Risskov d. 15/10 …` (uden "i" mellem vej og by)
- `2 indbrud på Reventlowsvej i Viby - gerningstid 18/10` (bliver til to indbrud)
- Flere indbrud skrevet i én linje, OCR-agtige fejl som `16/l0` og `kl. l0.59`, og stavefejl som `Riiskov` og `Århus N`.

Rettelser af bynavne ligger i `BY_ALIASER` i `parse.py`.

### Kommunestatistik for hele Jylland (Danmarks Statistik)

Tre af de fem jyske kredse udgiver ingen døgnrapporter, så kortet har et ekstra lag med **alle anmeldte indbrud i beboelse pr. jysk kommune pr. kvartal**. Tallene kommer fra Danmarks Statistiks åbne API: tabel `STRAF11` (overtrædelse 1320 "Indbrud i beboelser"), `FOLK1A` (befolkning) og `FAM55N` (husstande). `indbrudskort/statistik.py` henter de seneste 12 kvartaler (tre år) for kommunekoder 500–989 (de jyske kommuner) ved hver kørsel, finder kommunens midtpunkt via Nominatim (cachet) og gemmer `data/statistik.json`. Kører kun statistikken fejl, fortsætter resten. Brug `--uden-statistik` for at springe den over.

Husstande (beboede hjem) hentes fra `FAM55N`. På kortet kan man vælge, om cirkler, tal og kommunelisten skal vise **antal indbrud**, **pr. 1.000 indbyggere** eller **pr. 1.000 husstande**. Jo større og mørkere cirkel, jo højere tal. Laget kan slås fra, og man kan vælge periode: et helt kalenderår (det igangværende år vises som fx "2026 (1.–3. kvt.)" og sammenlignes med de samme kvartaler året før) eller et enkelt kvartal. Danmarks Statistik udgiver tallene ca. tre uger efter kvartalets udgang. Kommuner uden anmeldte indbrud i et kvartal står ikke i tabellen og vises som 0.

Under kortet er der en **graf over udviklingen pr. kvartal** for op til tre valgte kommuner (klik på en kommune på kortet eller i listen, eller vælg i feltet). Grafen følger valget af antal / pr. indbygger / pr. husstand, viser "Jylland i alt" som reference ved tallene pr. indbygger og husstand, og kan vises som tabel.

### Historik og egen langtidsstatistik

politi.dk's oversigt viser kun ca. 30 dage, men de ældre døgnrapporter ligger der stadig. Deres adresser følger faste mønstre (fx `.../oestjyllands-politi-uddrag-af-doegnrapporten-5-marts-2024/2024/03/05` eller `.../doegnrapport24082026/...`), som står som `historik`-skabeloner på kilden i `kilder.py`. Kommandoen

```bash
python -m indbrudskort historik --fra 2023-01-01 --til 2026-09-17
```

prøver skabelonerne dag for dag (ca. én forespørgsel pr. sekund), parser rapporterne og fletter dem ind uden dubletter. Dage uden rapport gemmes i `data/historik.json`, så en afbrudt kørsel kan fortsætte, hvor den slap. For Østjylland findes rapporterne mindst tilbage til 2022. Nordjyllands ældre rapporter har ingen gættelige adresser, så her vokser historikken fra dag til dag.

Ældre rapporter har andre formater (fx `På Hellerupvej 003 8000 Aarhus C …` eller `Tornhøjvej, 8260 Viby J, begået …`), som parseren også forstår. `Lager.normaliser()` køres ved hver gemning og retter allerede gemte poster, når parseren bliver forbedret, og fletter poster, der derved viser sig at være samme indbrud.

`indbrudskort/omraader.py` tæller indbruddene pr. område og pr. by/bydel pr. måned (efter rapportdato) i `data/omraader.json`. Kortsiden bruger filen i afsnittet **"Egen statistik fra døgnrapporterne"**: graf for op til tre områder eller bydele pr. måned, kvartal eller år, og en rangliste over de seneste 12 hele måneder sammenlignet med de 12 før.

Geokodning af mange nye veje tager tid (Nominatim tillader ét kald pr. sekund). Den daglige kørsel bruger derfor højst 20 minutter på geokodning (`--geokodning-minutter`), nyeste indbrud først, og tager resten de følgende dage. Statistikken pr. by/bydel kræver ikke koordinater.

### Postnumre, hotspots og ugens overblik

Hvert placeret indbrud får et **postnummer** (feltet `postnr`) ved et omvendt opslag i Nominatim ud fra punktet midt på vejen. Opslagene caches pr. ca. 100 m i `data/geokode-cache.json`, og den daglige kørsel bruger højst 10 minutter på dem (`--postnummer-minutter`). Indbrud, der kun er placeret ved byens midte, får byens postnummer.

**Hotspots** på kortsiden tæller indbrud pr. by/bydel, postnummer eller vej i de seneste 30, 90 eller 365 dage (efter rapportdato, regnet fra nyeste døgnrapport) og sammenligner med lige så mange dage før. Listen kan sorteres efter flest indbrud eller størst stigning. "Størst stigning" kræver mindst 2 indbrud i perioden, så ét enkelt indbrud et nyt sted ikke fylder listen.

**Ugens overblik** (`python -m indbrudskort ugerapport`) sammenligner de seneste 7 dages døgnrapporter med de 7 før og viser, hvor det steg mest pr. bydel, postnummer og vej, plus de jyske kommuner med størst stigning i Danmarks Statistiks seneste kvartal mod samme kvartal året før. Hver kørsel gemmer det i `data/ugerapport.json` til kortsiden.

### Indbrud nær mig og naboveje

Knappen **"Indbrud nær mig"** bruger telefonens eller computerens placering (browseren spørger om lov) og viser alle indbrud fra døgnrapporterne inden for **5 km** fra de seneste **14 dage**, nærmeste først. Kortet zoomer ind med en 5 km-cirkel. Placeringen bliver kun brugt i browseren og sendes ingen steder hen. Den kræver, at siden åbnes via https (det gør GitHub Pages).

Efter et indbrud er risikoen forhøjet i nabolaget i de følgende uger. Derfor viser popup'en og listen **naboveje**: vejene inden for ca. 500 m. De findes ved at slå vejnavnet op i 20 punkter i ringe på ca. 150, 300 og 500 m omkring indbruddet (omvendt opslag i Nominatim). Det sker for indbrud fra de seneste 30 dage, hvor vejen er kendt. Opslagene caches i `data/geokode-cache.json`, og den daglige kørsel bruger højst 8 minutter på dem (`--naboveje-minutter`). Listen er en stikprøve af vejene, så meget korte veje kan mangle.

### Afsnitsformatet (Nordjylland)

Et afsnit tæller med, når overskriften begynder med "Indbrud" (ikke "Tyveri", "Forsøg på indbrud" eller indbrud i biler). Fra brødtekstens første sætning hentes by/bydel ("i Vejgaard-området", "i Vesthimmerlands kommune", "i Aalborgs Vestby"), eventuel vej ("på Boysenbærvej"), antal ("i to villaer") og tidspunkt ("Natten til onsdag" omsat til seneste onsdag før rapportdatoen). Typen er *privat* (villa, lejlighed, fritidshus …), *erhverv* (butik, værksted, prøvehus, kirke …) eller *andet* (fx garage). Afsnittets tekst gemmes i feltet `beskrivelse` og vises på kortet.

### Dubletter

To linjer er det samme indbrud, hvis **vej + by + gerningstid** er ens. Der sammenlignes kun på datoer, fordi samme sag kan stå som "17/10" ét sted og "17/10 kl. 03.03" et andet. Den mest detaljerede gerningstid og den tidligste rapportdato bliver gemt, og alle kildelinks samles i `kilder`. To ens linjer i *samme* meddelelse er to forskellige indbrud.

### Geokodning

Status pr. oktober 2026:

- **DAWA er lukket.** `api.dataforsyningen.dk/vejstykker` og de andre DAWA-endpoints svarer `410 Gone`.
- **Dataforsyningens gsearch** (`/rest/gsearch/v2.0/navngivenvej`) virker, men kræver en gratis token. Den bruges først, når `DATAFORSYNINGEN_TOKEN` er sat. Koden er skrevet uden en token at teste med, så den læser svaret defensivt (GeoJSON eller WKT, og UTM32 bliver omregnet). Hvis svaret ikke kan bruges, falder den tilbage til Nominatim.
- **Datafordeleren** (DAR) kræver også login eller API-nøgle, og den gamle REST-tjeneste kan kun slå op på ID.
- **Nominatim (OpenStreetMap)** virker uden nøgle og er den kilde, der bruges i praksis. Der laves højst ét kald pr. sekund, og der sendes en User-Agent, som Nominatims brugsregler kræver.

Punktet sidder **halvvejs langs vejen**, beregnet ud fra hele vejens geometri, og aldrig ved et husnummer. Vejen skal ligge inden for 12 km af byens midte. Ellers er det sandsynligvis en anden vej med samme navn. Kan vejen ikke findes, bliver punktet sat ved byens midte med `"praecision": "by"` og vist med stiplet kant på kortet. Den slags opslag og mislykkede opslag prøves igen efter 14 dage. Alle opslag bliver gemt i `data/geokode-cache.json`.

### Dataformat (`data/indbrud.json`)

```json
{
  "opdateret": "2026-10-24T08:30:12+00:00",
  "antal": 53,
  "indbrud": [{
    "id": "3f2a…",
    "vej": "Klintevej", "by": "Hammel", "omraade": "Hammel", "type": "privat",
    "gerningstid": "14/10 – 18/10", "tid_fra": "2026-10-14", "tid_til": "2026-10-18",
    "rapportdato": "2026-10-19",
    "kilde_url": "https://politi.dk/oestjyllands-politi/doegnrapporter/…",
    "kilder": [{"url": "…", "titel": "…", "rapportdato": "2026-10-19", "udgiver": "politi.dk"}],
    "politikreds": "Østjyllands Politi",
    "lat": 56.26228, "lon": 9.861224, "praecision": "vej", "geokilde": "nominatim", "postnr": "8450"
  }],
  "behandlede_meddelelser": {"https://…": "2026-10-19"}
}
```

## Tilføj flere politikredse eller nyhedskilder

**En ny politikreds på politi.dk:** Tilføj en linje i `KILDER` i `indbrudskort/kilder.py`:

```python
PolitiDk("Midt- og Vestjyllands Politi", "Midt-og-Vestjyllands-Politi", "midt-og-vestjyllands-politi", format="afsnit"),
```

`format="liste"` bruges til Østjyllands faste liste og `format="afsnit"` til nyhedsafsnit som Nordjyllands.

Find distriktsnavnet i adressen, når du vælger kredsen på `https://politi.dk/doegnrapporter`, og stien i rapporternes egne links. Vær opmærksom på, at i dag er det kun Østjyllands Politi, der skriver en fast liste med *"indbrud i privat beboelse"*. Andre kredse skriver indbrud som almindelige nyhedsafsnit. Parseren finder kun listen, så der kommer ingen falske træffere, men der kommer heller ingen data, før den nye kreds' format er understøttet. Gør sådan her:

1. Gem 2–3 af kredsens rapporter i `tests/fixtures/` og skriv tests for, hvad der bør komme ud.
2. Udvid `find_indbrudslinjer`/`parse_linje` i `parse.py` (eller lav en egen parser til kredsen) til testene består.
3. Tilføj kredsens byer og bydele til `omraade_for`/`AARHUS_OMRAADE`, hvis områdefiltret skal samle dem.

**En ny politikreds på Via Ritzau:** Find udgiverens ID i adressen på kredsens nyhedsrum (`https://via.ritzau.dk/nyhedsrum/<id>/…`) og tilføj `Ritzau("Kredsens navn", <id>)` i `KILDER`.

**En helt anden nyhedskilde:** Lav en klasse i `kilder.py` med samme tre ting som de eksisterende:

- `udgiver` og `politikreds`
- `find(siden: date) -> list[Meddelelse]`
- `hent(meddelelse) -> str`, der returnerer HTML eller tekst

Tilføj den til `KILDER`. Resten (parsing, dubletter, geokodning og kortet) virker uden ændringer. Skriv tests med gemte eksempler, før kilden kommer med i den daglige kørsel.

## Begrænsninger

- Politiet oplyser højst vej og by. Kortet viser derfor *hvor i området* der har været indbrud, ikke adresser. Nordjyske indbrud sidder som regel ved byens eller kommunens midte.
- Dækningen er ujævn: Østjylland har alle anmeldte indbrud i privat beboelse, Nordjylland et udvalg, og de tre øvrige kredse næsten intet (se tabellen ovenfor).
- Enkelte døgnrapporter bliver udgivet som billeder (fx Via Ritzau 14/10 2026). De kan ikke læses og bliver sprunget over.
- I Østjyllands rapporter bruges kun listen; nyhedsafsnit som "Indbrud udviklede sig til røveri i Sabro" kommer ikke med (undtagen erhvervsindbruddet i Sabro fra prototypens startdata).
- Kortfliser © OpenStreetMaps bidragydere. Geokodning © OpenStreetMap via Nominatim.
