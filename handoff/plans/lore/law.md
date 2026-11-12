# LAW lens: a "prophetic voice" for Sauron (EU + France, as of 2026-11-07)

**This is not legal advice.** It is a research lens for the design. A lawyer (French financial law and press law) must check it before regime (b) MEMBERS or (c) PUBLIC goes live.

Scope: market-abuse law (MAR, MiCA), investment recommendations, the advice boundary (MiFID II), the French influencer law and the AMF/ESMA finfluencer positions, French defamation law. A few neighbouring rules are flagged in §7 (AI Act art. 50, DSA, LCEN legal notices, GDPR art. 10, consumer law). Tolkien IP, tax and company law are out of scope.

## How to read the tags

Each statement carries a source key in `[KEY]` (resolved to a URL in §10 and in `sources.md`) and a confidence tag:

- **V**: checked today against the primary text or an official page (through search excerpts of EUR-Lex, ESMA, AMF, CURIA or an "as adopted" mirror of the EU text).
- **S**: secondary source only (law firm, press, commentary); verify before relying on it.
- **K**: the legal text as I know it; **not** re-checked today (see the limit below); verify.
- **?**: my analysis or an open point; unsure.

**Limit of this research:** `WebFetch` could not reach `eur-lex.europa.eu` or `www.legislation.gov.uk` (host not allowed in this session's network), and Légifrance was not fetched either. Primary wording was confirmed through search excerpts only. The exact article wording (especially Delegated Regulation 2016/958 arts. 2, 4 and 6, loi n° 2023-451 art. 4 after the 2024 ordinance, and CMF L.465-3-2 penalties) should be re-read on EUR-Lex/Légifrance. To fetch them in a later run, `eur-lex.europa.eu` has to be allowed in the session's network settings.

---

## 0. Bottom line

1. **A view only the operator reads is not an "investment recommendation".** MAR's definition requires information "intended for distribution channels or for the public" [MAR-a3 · V]. Regime (a) PRIVATE is legally light. It must be **enforced in code**: `Notification.create_for_all` reaches every active account, so the day a second account exists, the same post becomes a (b) publication.
2. **As soon as anyone else reads it** (the Court, a Telegram group or channel, the newsletter, the Wall), any opinion on a named financial instrument, issuer, crypto-asset, or a tradable price target is an investment recommendation. It then needs MAR art. 20 + Delegated Regulation 2016/958: identity, facts kept apart from opinion, sources, forecasts labelled with their assumptions, date and time, and **disclosure of conflicts of interest** [MAR-a20 · V] [DR958 · V/K]. Sauron would likely count as an "expert" (it repeatedly proposes decisions and presents itself as expert), which adds duties [DR958-ch1 · V].
3. **The hard point: the bots trade the markets the voice talks about.** Voicing an opinion on an instrument after taking a position, then profiting from the price effect, without disclosing the conflict "simultaneously ... in a proper and effective way", is market manipulation ("scalping", MAR art. 12(2)(d)) [MAR-a12 · K/S]. The AMF has sanctioned exactly this pattern (2010; 2022) [MIGUET10 · S] [AMF-SAN22 · V]. Disclosing positions is excluded by the operator's own rules, so the only clean design is **never to voice instrument-level views on anything the operator or the bots hold, recently traded or may trade** (restricted list + silence window), and to keep the bots from trading on the voice.
4. **Macro "great forces" theses without a named instrument or issuer are generally not investment recommendations** (ESMA: such communications "should generally not be considered" recommendations, case by case; a sector of very few issuers can be) [Q1738 · V]. This is the natural ground for prophecies in (b) and (c).
5. **Never personal.** A recommendation presented as suitable for a member, or based on their situation, is investment advice and needs a licence (CIF/investment firm). Disclaimers do not cure it [DR565 · K] [ESMA-ADV23 · S] [ESMA-FF26 · S].
6. **Naming "manipulators" or "powers":** only documented, sourced facts (regulator decisions, court records, with date and appeal status), measured wording, no rumours, no natural persons by default. Companies can sue for defamation; a foreign State cannot [L1881 · S] [ETAT19 · S].
7. **Publishing machine-written text:** since 2 August 2026, AI-generated text published to inform the public on matters of public interest must be disclosed as such, unless a person holds editorial responsibility after human review [AIA · K] [AIA-ML · S]. Human review also protects against defamation and against "ought to have known" false information under MAR 12(1)(c).
8. **No paid promotion, ever.** Any payment from a broker or crypto platform (affiliate or referral) turns the voice into "influence commerciale" under loi n° 2023-451. The promotion of the riskiest financial contracts is banned, and crypto may be promoted only for providers authorised under MiCA (only those may serve in France since 1 July 2026) [DAJ-INFL · S] [AMF-MICA26 · V].

The "independence" the law favours is **independence from the trading book**: no trading on what it says, and it says nothing on what is traded. The independence it penalises is **publishing without a responsible human**.

---

## 1. When does a published market view become an "investment recommendation"?

### 1.1 The definitions

- **MAR art. 3(1)(35):** "investment recommendation" means *information recommending or suggesting an investment strategy, explicitly or implicitly, concerning one or several financial instruments or the issuers, including any opinion as to the present or future value or price of such instruments, intended for distribution channels or for the public* [MAR-a3 · V] [Q1737 · S].
- **MAR art. 3(1)(34):** "information recommending or suggesting an investment strategy" has two branches [MAR-a3 · V/K]:
  - **(i)** information produced by an independent analyst, an investment firm, a credit institution, *any other person whose main business is to produce investment recommendations*, or a natural person working for them, which *directly or indirectly* expresses a particular investment proposal in respect of a financial instrument **or an issuer**;
  - **(ii)** information produced by **anyone else**, which *directly proposes a particular investment decision* in respect of a financial instrument.
  - ESMA: the "main business" condition in (i) applies only to persons other than independent analysts, investment firms and credit institutions [Q1738 · S] [PLANET · S].
- **"Expert"** (Delegated Regulation 2016/958 art. 1(a)): a person in branch (ii) *who repeatedly proposes investment decisions in respect of financial instruments* and who (i) presents himself as having financial expertise or experience, or (ii) puts forward his recommendation in such a way that other persons would reasonably believe he has financial expertise or experience [DR958-ch1 · V (fragments)].
- **What that means for Sauron (?):** a software company whose AI voice ("the Eye") repeatedly proposes decisions and presents itself as an all-seeing market intelligence would most likely be an **expert** in branch (ii). If the Court or the prophecies became the company's **main business** (for example a paid subscription for market views), the AMF could argue branch (i). Branch (i) is wider: "directly or indirectly" and "issuer". Do not rely on the narrower wording of (ii).

### 1.2 How ESMA reads it

- **No instrument or issuer named:** such a communication "should generally not be considered an investment recommendation", assessed **case by case**. However, it can implicitly recommend instruments if a reasonable investor would infer that. ESMA's example: an opinion on a specific sector composed of a very limited number of issuers may be a recommendation on those issuers [Q1738 · V].
- **Valuation statements count:** material containing a valuation statement about an instrument's price (for example "overvalued", a quantitative fair value) implicitly recommends a strategy [Q1740 · S].
- **Purely factual information** about instruments or issuers (for example recent events or news) is not a recommendation, provided it does not explicitly or implicitly recommend or suggest a strategy [Q1741 · V].
- **Form is irrelevant:** oral, electronic or written; standardised communications pre-planned for distribution channels that suggest a strategy are in scope [Q1737 · S].
- **Social media is covered:** the rules apply wherever the content is aimed at a wide audience, including traditional and social media; breaches can lead to fines and to referral to prosecutors; misleading content can also be manipulation [ESMA-SM21 · V] [ESMA-SM21-PR · V]. The AMF publicly backed this reminder [AMF-SM21 · V].

### 1.3 Which instruments are in scope (MAR art. 2)

- MAR covers financial instruments admitted to trading (or with a request for admission) on an EU regulated market, MTF or OTF. It also covers instruments whose price or value depends on, or has an effect on, those instruments, **including CFDs and credit default swaps** (art. 2(1)(d)). It applies to any transaction, order or behaviour concerning them **whether or not it takes place on a trading venue** (art. 2(3)) [MAR · K].
- Many non-EU large caps are also admitted to trading on EU MTFs, which brings them into MAR. Check per instrument (?).
- **Spot FX is not a financial instrument** under MiFID II (Delegated Regulation 2017/565 art. 10). MAR does not cover spot FX, and ESMA postponed any extension. **FX derivatives and FX CFDs are financial instruments.** Whether an opinion on a currency pair falls under MAR therefore depends on links to derivatives in scope [FX · S] [FX2 · S] [DR565 · K]. **Unsure; treat as in scope by prudence.**
- **Commodities:** MAR reaches "related spot commodity contracts" for manipulation (art. 12) [MAR-a12 · V]. For recommendations, the definition speaks of "financial instruments or the issuers". An opinion on a commodity's price that implies trading its futures, ETCs or CFDs can be read as an implicit recommendation on those instruments (?). Treat a direction call or price target on a tradable commodity as a recommendation.
- **Crypto-assets:** MiCA Title VI (arts. 86-92) has its own market-abuse regime for crypto-assets admitted to trading on a crypto trading platform (or with a request for admission), whether or not the behaviour takes place on a platform [MiCA · K]. MiCA has **no equivalent of MAR art. 20**: no investment-recommendation formatting duties. It **does** prohibit manipulation, including the scalping case of art. 91(2)(d) (§3.3) [MiCA-91 · S].

### 1.4 Who the audience is decides the regime

| Audience | "Intended for distribution channels or for the public"? |
|---|---|
| The operator alone (his own tool, his own money) | **No.** Internal; not distributed (K). |
| Staff of the producer (today: the operator) | Generally internal (K/?). |
| Logged-in members (more than one person) | **Yes, most likely**: standardised, pre-planned communications to a group are in scope [Q1737 · S]; industry reading: "disseminated to more than one client" [ICMA · S]. |
| Public pages, social posts, a public Telegram channel | **Yes**: "for the public" [MAR-a3 · V] [ESMA-SM21 · V]. |

### 1.5 The ladder for a prophecy (design aid)

| What the text says | MAR status (b)/(c) | Risk |
|---|---|---|
| A thesis on forces (rates, energy, debt cycles, demography, geopolitics) with **no instrument, issuer, sector-of-few or tradable price target** | Generally **not** a recommendation [Q1738 · V] | Low |
| Signposts on **public statistics** (a policy rate decision, an inflation print, a debt ratio) with a deadline | Not about an instrument's price (?) | Low |
| A broad theme or sector ("banks", "energy transition") with no direction call | Gray; a sector with very few issuers = recommendation [Q1738 · V] | Medium |
| A **price level or direction** for an index, a commodity or a currency pair, no instrument named | Gray; likely implicit (index futures, ETFs, ETCs, CFDs exist) (?) | Medium-high |
| A named stock, ETF, issuer, pair, contract or crypto **with a direction, a target or a valuation word** | **Yes** (MiCA for crypto: no art. 20, but art. 91 applies) | High |
| Relaying a third party's current call ("fund X says buy Y") | **Dissemination** of a recommendation: arts. 8-9 of 2016/958 (identify the disseminator; flag alterations) [DR958 · K] | High |
| A documented history of a strategy or a manipulation case, with sources | Factual history, not a recommendation [Q1741 · V]; defamation rules apply (§5) | Low-medium |

### 1.6 The advice boundary (MiFID II): never cross it

- Investment advice is the provision of **personal recommendations** to a client. A recommendation is personal if it is presented as **suitable** for that person or is **based on a consideration of their circumstances**. "A recommendation is not a personal recommendation if it is issued exclusively to the public" [MiFID2 · K] [DR565 art. 9 · K].
- ESMA's 2023 supervisory briefing: recommendations made through **websites, investment apps or social media (including influencers) could, in certain instances, be personal recommendations**. A disclaimer saying "no advice is given" does not prevent a recommendation from being found. Access to model portfolios or copy trading may also be advice, depending on the circumstances [ESMA-ADV23 · S].
- ESMA/AMF finfluencer factsheet (January 2026): telling people what to buy or avoid can be investment advice requiring authorisation; "this is not investment advice" disclaimers do not protect you [ESMA-FF26 · S] [AMF-FF26 · V].
- In France, personal investment advice needs the status of an investment firm or of a *conseiller en investissements financiers* (CIF) [K]. Managing others' money or executing for them (copy trading, "mirror the bots") is an investment service needing authorisation: the operator's **AMF red line** [K].
- By contrast, general research or "general recommendations" not addressed to a person are a MiFID **ancillary** service (Annex I, Section B(5)), which on its own needs no licence. MAR art. 20 still applies [MiFID2 · K].

---

## 2. Duties when it is a recommendation (MAR art. 20 + Delegated Regulation 2016/958)

**MAR art. 20(1):** persons who produce or disseminate investment recommendations or other information recommending or suggesting an investment strategy *shall take reasonable care to ensure that such information is objectively presented, and to disclose their interests or indicate conflicts of interest concerning the financial instruments to which that information relates* [MAR-a20 · V].

### 2.1 Identity of the producer (2016/958 art. 2)
- Every recommendation must show clearly and prominently who produced it: the **name and job title of the individual who prepared it**, and the **legal person** responsible where applicable [DR958 · K] [SKAD26 · S].
- **Open point (?):** for AI-produced text, who is "the individual who prepared" it? The prudent reading: name the company and the human who reviews and approves each publication. This **collides with the house rule "no name"** on the public pages (`core/book_content.py` rules). Either the public voice stays below the recommendation line (macro only), or a responsible person must be named. Ask the lawyer.

### 2.2 Objective presentation (2016/958 art. 3: every producer)
Producers take reasonable care that:
- **(a)** facts are clearly distinguished from interpretations, estimates, opinions and other non-factual information [DR958-a3 · V];
- **(b)** all substantially material sources are clearly and prominently indicated [K] [SKAD26 · S];
- **(c)** sources are reliable, or any doubt about reliability is clearly indicated [K];
- **(d)** all projections, forecasts and price targets are clearly and prominently labelled as such, with the material assumptions made in producing or using them [DR958-a3 · V];
- **(e)** the date and time when production was completed are clearly and prominently indicated [K] [SKAD26 · S].
- Likely also: be able to **substantiate** a recommendation on request of the competent authority (K?; article to confirm).

**Note for the design (?):** the Lore's grammar already maps onto this article. "Documented" vs "reputed" corresponds to facts vs opinions and reliable vs doubtful sources. "Breaks when" corresponds to material assumptions and sensitivity. Evidence grades correspond to source reliability. A prophecy format built on the Lore's claim sides would meet art. 3 almost by construction.

### 2.3 Additional duties for experts and professionals (2016/958 art. 4: K, list to verify)
In addition to art. 3, a person in branch (i) or an **expert** must include (as I recall the text):
- a summary of the valuation basis or methodology and its assumptions, and where the details can be found;
- the **meaning** of any call ("buy", "sell", "hold"), possibly with the **time horizon** and an appropriate **risk warning**, including a sensitivity analysis of the assumptions;
- the planned **frequency of updates**;
- where the recommendation differs from a previous one on the same instrument or issuer in the preceding 12 months, the change and the date of the earlier one;
- a **list of all its recommendations over the preceding 12 months** (date, direction, price target and market price at dissemination, validity). Some items may be given by a clear reference, such as a link, where showing them in full would be disproportionate to the length of the recommendation [K?].
- A dated, immutable, graded "book of prophecies" (map_voices §4, point 4) would serve as this 12-month record.

### 2.4 Conflicts of interest (2016/958 arts. 5-6)
- **Art. 5 (everyone):** disclose in the recommendation *all relationships and circumstances that may reasonably be expected to impair the objectivity of the recommendation*. This includes interests or conflicts of interest of the producer and of any person working for it who was involved, concerning any financial instrument or issuer to which it relates directly or indirectly [DR958-ch2 · V]. Disclosures must be specific enough for the reader to take an informed view of the degree and nature of the interest (recital) [S].
- **Art. 6 (experts and professionals):** in addition, specific items, for example a net long or short position above **0.5 % of the issuer's total issued share capital**, stating whether it is long or short [DR958 · S]. These thresholds will not bite at an individual's size. **Art. 5 still catches any position** that may impair objectivity (?).
- **French precedent, conflict through closely associated persons:** in March 2022 the AMF Enforcement Committee sanctioned a press company and its director for publishing investment recommendations **without mentioning their conflicts of interest**, and for price manipulation (as the release title says). The AMF's date is 4 or 11 March 2022; sources differ. The Committee held that holdings of the same security by persons closely associated with the author, on the publication dates, were a conflict of interest that had to be disclosed. The online versions mentioned neither the portfolio nor the conflict [AMF-SAN22 · V] [AMF-SAN22-FR · V]. Earlier (decision of 16 December 2010), the AMF had for the first time sanctioned someone for recommending securities in which he had invested without disclosing that conflict [MIGUET10 · S].

### 2.5 "Sauron trades its own account: disclose positions?"
- **Legally:** if the voice publishes a recommendation on an instrument in which the operator (or the company, or the bots on his account) holds a position or has a trading interest, art. 5 requires disclosure, and MAR 12(2)(d) makes simultaneous, proper and effective disclosure the only safe way to trade around it (§3.2).
- **Generic boilerplate** ("the platform and its founder may hold or trade any instrument mentioned, in either direction") is **probably not enough** when an actual position exists. The recital wants the degree and nature of the interest (?).
- **The operator's rules forbid disclosing positions.** The design consequence: a **restricted list** (no member or public recommendation on any instrument held, traded in the last N days, or eligible for the bots in the next M days) and a **silence window** (no trading in a named instrument for a period before and after publication). The lawyer should set N and M.
- **The firewall already exists in spirit:** `lore/policy.py` keeps everything under `bot_program/` and `portfolio/` from reading the Lore. The prophetic voice needs the same separation in both directions: the bots never read its instrument calls, and it never names the bots' instruments.

### 2.6 Dissemination of third-party recommendations (2016/958 arts. 8-9: K)
Relaying someone else's current recommendation, for example from a "world" Lore entry about a fund's live call, requires the disseminator's identity, clear indication of any substantial alteration, and rules for summaries and extracts [DR958 · K] [FCA-958-a9 · S]. Describing a fund's **historical, documented** strategy is history, not dissemination (?).

### 2.7 The record kept
- Keep, for each member or public publication: the exact text, a timestamp (hash-chained like the audit chain), the sources, the model and prompt version, the human approver, the instruments named, and the trading activity in those instruments over a window around the publication. This supports art. 3 (date and time; substantiation), art. 4 (the 12-month list), and the defence against any 12(2)(d) suspicion (?).
- ESMA's May 2024 statement on AI in investment services asks MiFID firms for transparency about the role of AI, governance and record-keeping. Sauron is not a MiFID firm, but it is the supervisors' frame for AI output [ESMA-AI24 · V].

### 2.8 Sanctions
- MAR minimum maximum fines for an art. 20 breach: **€500,000** (natural persons) and **€1,000,000** (legal persons). For arts. 14-15: €5,000,000 and €15,000,000 or 15 % of turnover [MAR-a30 · V]. France can go higher: the AMF Enforcement Committee can impose up to **€100 million or ten times the profit** for market abuse (CMF L.621-15) [K].

---

## 3. Manipulation (MAR art. 12) and what it means for a platform whose bots trade what it talks about

### 3.1 False or misleading information: art. 12(1)(c)
- Manipulation includes *disseminating information through the media, including the internet, or by any other means, which gives, or is likely to give, false or misleading signals as to the supply of, demand for, or price of, a financial instrument* (or a related spot commodity contract), or fixes prices at an abnormal or artificial level, **including the dissemination of rumours**, *where the person who made the dissemination knew, or ought to have known, that the information was false or misleading* [MAR-a12 · V].
- "Ought to have known" is objective. The UK regulator's guidance on the same text: the test is what a normal and reasonable person would have known; effective arrangements may show one could not reasonably have known [FCA-MAR18 · S, UK guidance, used here as an analogy].
- **For an AI voice (?):** LLM confabulation is a known risk. Publishing unchecked factual claims about an issuer to members or the public, without fact-checking arrangements, is the textbook "ought to have known" exposure. Hence: no factual claim about an issuer without a source; "reputed" claims labelled; no rumours.
- **France, criminal law:** CMF L.465-3-2 punishes the dissemination, by any means, of information giving false or misleading indications. The penalties are those of L.465-1 I A (as I know it: up to 5 years' imprisonment and €100 million, or up to ten times the profit) [CMF-465 · S] [K for the amounts]. It is a **formal offence**: an actual effect on prices need not be shown [ACI · S]. It was amended by ordinance n° 2024-936 of 15 October 2024 (MiCA adaptation; scope extension to crypto-assets likely, to verify) [CMF-465 · S].
- **AMF practice:** an individual posting positive messages under a pseudonym on a retail stock forum was fined **€75,000** for price manipulation (the Collège had sought €350,000) [AMF-FORUM · S]. The AMF warns investors to distrust opinions whose authors do not state their positions [AMF-SURV · S].

### 3.2 Scalping: art. 12(2)(d)
- Manipulation includes *taking advantage of occasional or regular access to the traditional or electronic media by voicing an opinion about a financial instrument ... (or indirectly about its issuer) while having previously taken positions on that financial instrument ... and profiting subsequently from the impact of the opinions voiced on the price of that instrument ..., without having simultaneously disclosed that conflict of interest to the public in a proper and effective way* [MAR · K] [MAR-a12 · V for the article] (the MiCA twin wording in [MiCA-91 · S] matches).
- The elements are: (1) a **prior position**; (2) an **opinion voiced** through a medium the person has access to (a members' space or a public page qualifies, ?); (3) **profit** from the price impact; (4) **no simultaneous, proper and effective disclosure**.
- **Journalism carve-out unavailable:** MAR art. 21 assesses journalistic dissemination under press-freedom rules, **unless** the persons concerned or persons closely associated with them derive, directly or indirectly, an advantage or profits from it, or intend to mislead the market [MAR-a21 · V]. A platform whose owner trades the instruments discussed cannot rely on art. 21.

### 3.3 Crypto: MiCA art. 91
- MiCA art. 91 prohibits market manipulation in crypto-assets, including the same scalping case: voicing an opinion about a crypto-asset after taking positions, profiting from the impact, without having simultaneously disclosed the conflict to the public in a proper and effective way (art. 91(2)(d)) [MiCA-91 · S] [MiCA · K].
- Since **1 July 2026**, only crypto-asset service providers authorised under MiCA may serve clients in France (end of the PSAN transitional period) [AMF-MICA26 · V].

### 3.4 What this means for Sauron (?)
1. **Firewall both ways.** The voice's instrument-level calls are never an input to the bots (consistent with `lore/policy.py`'s deny list), and the voice never names what the book holds or trades.
2. **Restricted list + silence window** around any instrument named to members or the public (§2.5).
3. **No front-running.** No bot or manual trade in a named instrument between drafting and publication. Once an audience is large, the content of a forthcoming recommendation could itself become price-sensitive (?).
4. **Fact gate.** Factual claims about issuers must be sourced, checked and dated; rumours are excluded; "reputed" claims are labelled as such.
5. **Members' own calls.** If the Court hosts members' instrument predictions or "support/fear" votes, ban coordinated pumping in the terms of use and do not amplify member calls as Sauron's own "consensus buy" (?).
6. **Small size is no defence.** The offences of 12(1)(c) (and French L.465-3-2) do not need a proven price effect [ACI · S]. The AMF sanctions individuals as well as firms [AMF-FORUM · S].

---

## 4. The French influencer law and the AMF/ESMA positions on finfluencers

### 4.1 Loi n° 2023-451 du 9 juin 2023 (as amended by ordonnance n° 2024-978 du 6 novembre 2024)
- **Who is an influencer (art. 1):** natural **or legal** persons who, **in return for consideration** (*à titre onéreux*), use their notoriety with their audience to communicate to the public **by electronic means** content aimed at promoting, directly or indirectly, goods, services or any cause [LOI-INFL · S] [L-GBD · S]. Article 1 was **rewritten** by the 2024 ordinance (adopted to bring the law into line with EU law: the e-commerce, audiovisual media services and unfair commercial practices directives). The new wording was not checked today [ORD-2024 · S] [ORD-2024-D · S].
- **Commercial intent:** the ordinance relaxed the labelling duty. An "equivalent mention adapted to the format" is allowed, and omission is a misleading practice only where the commercial intent does not already appear from the context [ORD-2024-LR · S].
- **Financial promotion bans:** the law extended to influencers the ban on electronic advertising for the **riskiest financial contracts** (those defined in CMF L.533-12-7: the forex/CFD/binary-option family, through Code de la consommation L.222-16-1). It also banned influencers from promoting **digital-asset** services and offerings unless the provider is registered or authorised. Breaches carry an administrative fine (up to €100,000 per the government's summary) [DAJ-INFL · S] [SENAT-INFL · S] [CMF-533 · S]. ESMA's French factsheet summarises it plainly: in France, influencers may not promote certain particularly risky CFDs [ESMA-FF26 · S]. The exact current wording of art. 4 (after the ordinance and MiCA) is **unverified**.

### 4.2 ESMA and AMF positions on finfluencers
- **2021:** ESMA's statement on investment recommendations on social media. MAR applies to anyone recommending to a wide audience: disclose identity, present objectively, disclose conflicts [ESMA-SM21 · V]. The AMF backed it [AMF-SM21 · V].
- **January 2026:** ESMA and the AMF published a factsheet for finfluencers. Its tips: be honest and clear; do not fake or mislead; **do not give advice** (personal recommendations need authorisation; disclaimers do not protect); **disclose any payment** (paid partnerships labelled as advertising); post responsibly (MAR applies) [AMF-FF26 · V] [ESMA-FF26 · S] [MWE26 · S].
- **AMF + ARPP "Certificat de l'influence responsable" (finance module):** voluntary; updated in 2025 for MiCA and the influencer law. The AMF urges financial firms that use influencers to choose certified ones [AMF-CERT · V].
- **July 2026:** the AMF published a study of the influence of the X network on retail investors in CAC 40 stocks (January-November 2024): volume of messages matters more than content, and younger investors and neo-broker clients react about twice as strongly. This is a sign of supervisory focus [AMF-X26 · V].
- **EU Retail Investment Strategy:** political agreement in December 2025. It adds MiFID II rules making firms responsible for finfluencers acting for them (written agreements, monitoring). The Council approved in June 2026. The Parliament's final vote and publication in the Official Journal were **not confirmed** by this research [RIS · S] [SKAD26 · S]. These rules target firms that pay finfluencers, so they would matter to Sauron only if it were paid by one.

### 4.3 Does it apply to Sauron's voice?

| Situation | Influencer law | MAR / AMF-ESMA |
|---|---|---|
| Sauron's AI voice speaking to its **own members** about markets, no third party paying | **No** "influence commerciale": no consideration from a third party for promotion (?). Sauron promoting **itself** is ordinary advertising, which must be identifiable as such and identify the advertiser (LCEN art. 20) [K], and must comply with consumer law (§7) | **Yes**, if instrument-level (§1-3) |
| The same on **public pages** (the Book, the Wall) | Same as above | **Yes** |
| A **Telegram channel** (public) or group (members) | Telegram is "electronic means". Same answer: no payment, no influencer regime | Channel = public; group = distribution channel (§1.4) |
| Any **affiliate, referral or partner payment** from a broker, an exchange or a crypto platform, including benefits in kind | **Yes**: a legal person can be an influencer. Labelling applies; promotion of the riskiest CFDs is banned; crypto only for authorised providers [DAJ-INFL · S] | Yes, plus the conflict of interest (payment) to disclose [ESMA-FF26 · S] |

**Never** put a broker's referral link or a paid partnership in the prophetic voice.

---

## 5. Defamation in France (loi du 29 juillet 1881) when naming "manipulators" or "powers"

### 5.1 The rules
- **Definition (art. 29):** any allegation or imputation of a **precise fact** that harms the honour or reputation of the person or body to which it is imputed. Insult (*injure*) is an outrageous expression containing no imputation of fact [L1881 · S]. **Legal persons** (companies, funds, banks) can be defamed. Criticism aimed at the company itself (for example imputing malpractice) is defamation; criticism of its **products or services** is *dénigrement* (civil fault) instead [DENIG · S] [DENIG19 · S].
- **Penalty and time limit:** public defamation of a private person (including a company) carries a fine of **€12,000** (art. 32). Prosecution is time-barred **three months** after publication (art. 65) [L1881 · S]. Public bodies ("cours, tribunaux, armées, corps constitués, administrations publiques") are protected by art. 30 [K].
- **A foreign State cannot sue for defamation** in France: it is not a "particulier" under art. 32 (Cass., Ass. plén., 10 May 2019; QPC not referred, 17 December 2018) [ETAT19 · S] [ETAT19b · S].
- **Defences:**
  - **Proof of truth** (art. 35): it must be offered within 10 days of the summons (art. 55), with an exception for private life [K].
  - **Good faith:** legitimate aim, absence of personal animosity, serious inquiry, and prudence and measure in expression. Where the words are part of a **debate of general interest** and rest on a **sufficient factual basis**, the criteria are applied less strictly (Civ. 1re, 11 May 2022, n° 21-16.497; Crim., 5 September 2023, n° 22-84.763) [BF22 · S] [BF23 · S].
- **Dénigrement** of a product or service is excused if the information concerns a subject of general interest, rests on a sufficient factual basis and is expressed with some measure (Cass. com., 9 January 2019, n° 17-18.350, as cited by commentators) [DENIG19 · S].
- **Presumption of innocence** (Code civil art. 9-1): presenting a person **as guilty** of facts under investigation before any conviction can be ordered corrected, including in summary proceedings, at the cost of the person responsible, natural or legal [K].

### 5.2 Public or not? Who is liable?
- **"Public" vs "non-public":** remarks on an account open only to persons approved by the author, **very few in number** and forming a **community of interests**, are not public (Civ. 1re, 10 April 2013, n° 11-19.530). A non-public offence is still an offence (petty) [CI13 · S]. A members' area that anyone can join, paid or not, is unlikely to be a community of interests, so treat **the Court as public** for defamation (?).
- **The publisher:** the director of publication of an online service run by a legal person is its **legal representative**, in this case the operator (Cass. crim., 22 January 2019 and 26 March 2019, as reported) [LCEN-ML · S]. Under art. 93-3 of loi n° 82-652, the director is liable as **principal author** when the message was **fixed before** being communicated to the public. For **contributions by users** in a space open to them, the director is liable only if aware of the message before it went online or if he did not act promptly to remove it once aware [93-3 · S] [QPC11 · S].
- **AI-written text (?):** in 2013 the Cour de cassation cleared Google for its autocomplete suggestions ("Google Suggest") as the result of a purely automatic process, random in its results, excluding any will to emit the words [GSUGG13 · S]. A prophetic voice that the company deliberately writes, publishes and brands as "Sauron's" is **its own speech**; do not count on that precedent. Whether AI text auto-published without review is "fixed beforehand" is unsettled. Human review settles it (the reviewer's company publishes it) and, above all, prevents the defamation.

### 5.3 Naming natural persons: data protection
- Data on offences that are criminal in substance are protected by GDPR art. 10. The CJEU read "criminal offences" autonomously and found even road-traffic penalty points covered, and found public disclosure of them unlawful (C-439/19, 22 June 2021) [CJEU-439 · V]. AMF market-abuse sanctions are often treated as criminal in substance (?). The AMF keeps its decisions online for at least five years; parliamentary texts and AMF practice indicate that personal data in decisions are not kept beyond five years (exact rule to verify) [AMF-PUB · S].
- **Consequence (?):** a "manipulations" pillar should name **institutions and decisions**, not individuals. Where a regulator anonymised or removed a name, do the same.

### 5.4 Safe and unsafe (for (b) and (c))

| Safer | Unsafe |
|---|---|
| "The AMF Enforcement Committee sanctioned company X on [date] for [breach as worded in the decision]; X has appealed / the decision is final" + link | "X manipulates the market", "the X cartel", "X rigs prices", with no decision |
| Quoting the operative wording of a regulator or court decision; competition-authority or court fines; published settlements, described as settlements | Rumours, "reputed" claims or anonymous posts presented as facts |
| Explaining **documented mechanisms** (spoofing, benchmark rigging, pump-and-dump) with past, sourced cases | Pending investigations framed as guilt (presumption of innocence) |
| Opinions clearly marked as opinions, with measure, on a subject of general interest | Mockery or insults of named people; attributing motives as fact |
| Criticising **States, central banks, policies** as policy (a foreign State cannot sue; French public bodies can) | Accusing named French public officials or bodies of offences |
| Naming legal persons with a sufficient factual basis | Naming natural persons for offences (GDPR art. 10; art. 9-1 C. civ.) |

---

## 6. Three regimes for Sauron's prophetic voice

### (a) PRIVATE: only the operator reads it (today: one account)

**Legal status.** Not "intended for distribution channels or for the public", so not an investment recommendation under MAR art. 3(1)(35), and MAR art. 20 does not apply [MAR-a3 · V]. No client, so no investment advice [K]. Defamation needs publicity or a third-party recipient [K]. The AI Act art. 50(4) duty applies to *published* text [AIA · K]. MAR art. 12 still governs his **trading** (not the voice).

**Allowed:** anything useful to him, including named instruments, directions, targets, his own book, "reputed" hypotheses, and unproven manipulation theories, clearly marked as such for his own judgement.

**Conditions:**
- **Make "private" a code fact, not a circumstance:** an audience check at send time, so the voice reaches only the operator's account. `Notification.create_for_all` (used by `agent_commentator`) posts to every active account: the day a second account exists (staff, keeper, investor, tester), the voice is a (b) publication.
- Never route it to the `telegram_eye` group (anyone in that chat), the newsletter, the strategist briefing fan-out, the Book or the Wall.
- Keep a dated internal record anyway; it costs nothing and shows what the private record said, and when, if (b) starts later.

**Never:**
- Forward, screenshot or paste it to anyone without passing the (b)/(c) gates; one forward to a group is dissemination.
- Use it to advise, or to trade for, anyone else (the AMF red line).

### (b) MEMBERS: logged-in members (the Court)

**Legal status.** A distribution channel: any instrument-level view is an investment recommendation [Q1737 · S] [ICMA · S]. Sauron is likely an "expert" [DR958-ch1 · V]. MAR 12(1)(c) and 12(2)(d) apply fully. For defamation the space is probably public (§5.2). The platform hosts members' posts (DSA hosting rules, §7). Personal advice is the bright line (§1.6).

**Allowed (low risk):**
- Theses on great forces without instrument, issuer, sector-of-few or tradable price target [Q1738 · V].
- Signposts on **public statistics** with deadlines and honest grading, including "unresolvable".
- Documented histories of manipulation and power mechanisms with sources (§5.4), and Lore-backed explanations of how strategies worked.
- Members discussing themes, under moderation and terms of use.

**Allowed only with the full MAR kit, the restricted list and the silence window (medium-high risk; lawyer first):**
- Instrument, issuer, pair, commodity or crypto views. The kit: identity (company + responsible person, ?); facts vs opinion; sources and their reliability; forecasts labelled with assumptions; date and time; meaning, horizon and risk; changes since the last call; the 12-month list; conflicts per art. 5-6; and the record (§2.7).

**Never:**
- A **personal** recommendation to a member ("for you", "in your portfolio", answers that take their situation into account): that is investment advice and needs a licence; disclaimers do not cure it [ESMA-ADV23 · S] [ESMA-FF26 · S].
- Instrument views on anything the operator or the bots hold, recently traded or may trade, unless the conflict is disclosed simultaneously, properly and effectively. The operator's rules exclude that disclosure, so **never** [MAR · K] [AMF-SAN22 · V].
- Unchecked factual claims about issuers, rumours, "reputed" claims presented as fact (12(1)(c)) [MAR-a12 · V].
- Naming natural persons as manipulators; accusing anyone of an offence without a final decision (§5).
- "Copy Sauron", mirroring the bots, auto-executed signals, pooled money (investment services; the AMF red line) [ESMA-ADV23 · S] [K].
- Promising or implying returns; cherry-picked hit rates (consumer law, §7).
- Affiliate or paid links to brokers or crypto platforms (§4.3).
- Amplifying members' instrument calls as Sauron's own consensus (?).

### (c) PUBLIC: the Book, the Wall, social posts, a Telegram channel

**Legal status.** Everything in (b), plus: clearly "for the public" under MAR; the ESMA social-media statement and the 2026 finfluencer factsheet apply squarely [ESMA-SM21 · V] [AMF-FF26 · V]; public defamation in full; AI Act art. 50(4) labelling for AI-generated text on matters of public interest, unless a person holds editorial responsibility after human review (since 2 August 2026) [AIA · K] [AIA-ML · S] [AIA-RG · S]; LCEN legal notices on the site (§7).

**Allowed:**
- Macro theses on forces; signposts on public statistics.
- A **complete** graded record of past prophecies, misses included. The Wall's own rule, "claims nothing until the first calls come due", is the right consumer-law posture.
- The platform's story; documented histories (§5.4).

**Conditions:**
- **Human review and named editorial responsibility** before each publication. This gives the AI Act exemption and the defamation and 12(1)(c) safeguards together. Otherwise, label the text as AI-generated. Labelling it anyway is the simplest.
- A dated, immutable archive (hash) and a corrections policy; the existing leak walk (`core/leak_walk.py`) and the Book's rules (no account figure, no ticker held).
- **Default: no instrument-level calls in public.** If ever wanted: full MAR kit, restricted list, silence window, lawyer sign-off. Accept that the art. 2 identity duty conflicts with the "no name" rule (§2.1).

**Never:**
- Everything listed under (b).
- Instrument "teasers" ("the Eye sees X falling"): an implicit recommendation and potentially a misleading signal [Q1740 · S] [MAR-a12 · V].
- Any hint of the operator's holdings.
- Promotion of the riskiest CFDs (banned electronic advertising) or of crypto services that are not MiCA-authorised [DAJ-INFL · S] [AMF-MICA26 · V].
- Posting the voice in the `telegram_eye` group: it carries `/positions` and the brake (map_voices). A public Telegram **channel** is (c); a vetted members' group is (b).

---

## 7. Neighbouring rules to put on the lawyer's list (short)

- **AI Act art. 50(4)** (Regulation (EU) 2024/1689): deployers who publish AI-generated text "with the purpose of informing the public on matters of public interest" must disclose it, unless the text underwent human review or editorial control and a person holds editorial responsibility. It applies from **2 August 2026** [AIA · K] [AIA-ML · S]. Secondary sources say the Digital Omnibus (provisional agreement of 7 May 2026) left 50(4) on time, and may have moved only the 50(2) marking duty; they differ on details [AIA-RG · S] (?). Whether macro or market commentary is a "matter of public interest" is open (?).
- **DSA** (Regulation (EU) 2022/2065) for the Court if members post: hosting liability exemption (art. 6), notice-and-action (art. 16) for all hosts. The "online platform" duties exempt micro and small enterprises (art. 19) [DSA · K].
- **LCEN legal notices:** since the SREN law (21 May 2024) the publisher identification duty sits in LCEN art. 1-1 (formerly art. 6 III). A company's site must identify the company and its **director of publication** (its legal representative). The public Book and Wall need it whatever their "no name" content rule says [LCEN-ML · S]. Online advertising must be identifiable as such (LCEN art. 20) [K].
- **Consumer law** (Code de la consommation L.121-2 ff., misleading commercial practices): accuracy claims about prophecies used to sell a membership must be fair and complete; no promise of returns [K].
- **GDPR art. 10** if natural persons and their sanctions are named (§5.3) [CJEU-439 · V].
- **French "analyste financier" provisions** (CMF L.544-1 ff.): whether they still add duties for a company that regularly publishes opinions on listed issuers. Not verified today [K?].
- **Listing Act** (Regulation (EU) 2024/2809) amended MAR (insider lists, soundings, PDMR dealings, disclosure of protracted processes). The summaries found do not mention art. 20 or art. 12 [LISTING · S]. Re-read the consolidated text (?).

---

## 8. Questions for the lawyer (before (b) or (c))

1. Is Sauron (a software company with an AI voice, whose founder trades) an "expert" under 2016/958 art. 1(a)? Would a paid Court make producing recommendations its "main business" (branch (i))? Which art. 4 and art. 6 items then apply?
2. Identity for AI-produced recommendations: is the company plus a role enough, or must a natural person's name and job title appear? How does that fit the public pages' "no name" rule?
3. Is a generic conflicts statement ever enough, or are a restricted list and a silence window required? Which windows before and after publication would satisfy the AMF against 12(2)(d)?
4. Are price-level forecasts on indices, commodities and currency pairs, with no instrument named, "investment recommendations"? Spot FX vs FX CFDs?
5. Is the Court a "distribution channel" (MAR) and "public" (loi 1881)? Would a small, vetted, unpaid circle change either answer?
6. Defamation and AI text: who is the principal author; is auto-published AI text "fixed beforehand" (art. 93-3); what changes with human review?
7. AI Act art. 50(4): is market or macro commentary a "matter of public interest"? Does the operator's review meet the editorial-responsibility exemption?
8. Would any partnership with a broker (affiliate, referral, copy programme) turn the voice into "influence commerciale"? How does it interact with Code conso L.222-16-1 and CMF L.533-12-7?
9. GDPR art. 10 and the "manipulations" pillar: may sanctioned natural persons be named, and for how long?
10. LCEN art. 1-1 legal notices on the Book and the Wall.
11. CMF L.544-1 ff. (financial analysts): still relevant?
12. DSA and LCEN duties if members post in the Court; terms of use against coordinated pumping.

---

## 9. Résumé pour toi (FR)

- Tant que toi seul lis la voix prophétique, le droit des marchés ne la voit pas : une « recommandation d'investissement » (MAR) doit être destinée au public ou à des « canaux de distribution ». Ce privé doit être verrouillé dans le code (un seul destinataire), pas seulement vrai aujourd'hui : `Notification.create_for_all` touche tous les comptes.
- Dès qu'une deuxième personne la lit (la Cour, un groupe Telegram, la newsletter, le Wall), chaque avis sur un instrument nommé (action, paire, matière première, crypto) devient une recommandation. Il faut alors : identité, faits séparés des opinions, sources, prévisions étiquetées avec leurs hypothèses, date et heure, et surtout tes conflits d'intérêts.
- Le point dur : tes bots tradent les mêmes marchés. Parler d'un instrument qu'on détient, puis profiter de l'effet sur le cours sans l'avoir dit, c'est du « scalping » (MAR 12(2)(d)), donc une manipulation. L'AMF l'a déjà sanctionné (2010, 2022). Comme tu ne veux pas publier tes positions, la règle simple : la voix ne parle jamais aux autres d'un instrument que tu détiens ou que les bots tradent (liste restreinte + période de silence), et les bots ne tradent jamais sur ce qu'elle dit.
- Les grandes forces (taux, énergie, dette, géopolitique) sans instrument nommé ne sont en principe pas des recommandations (ESMA) : c'est le terrain naturel des prophéties pour la Cour et le public.
- Jamais de conseil personnalisé à un membre (c'est du conseil en investissement : il faut un agrément, et un avertissement ne suffit pas). Jamais de « copie Sauron ». Jamais de promesse de gain. Jamais de lien affilié vers un courtier (loi influenceurs + interdiction de pub pour les CFD les plus risqués).
- « Manipulateurs » et « puissances » : seulement des faits documentés (décisions AMF, jugements, avec date et statut d'appel), un ton mesuré, pas de rumeur, pas de personne physique nommée. Une société peut te poursuivre en diffamation ; un État étranger, non.
- Texte écrit par l'IA et publié : depuis le 2 août 2026, il doit être signalé comme tel, sauf relecture humaine avec responsabilité éditoriale. La relecture te protège aussi contre la diffamation et la fausse information.
- L'« indépendance » que le droit aime : la voix indépendante du trading. Celle qu'il punit : publier sans humain responsable.
- Avant (b) la Cour ou (c) le public, un avocat (droit financier + droit de la presse) doit valider. Ceci n'est pas un avis juridique.

---

## 10. Source keys (full list with what each supports: `sources.md`)

| Key | URL |
|---|---|
| MAR | https://eur-lex.europa.eu/eli/reg/2014/596/oj/eng |
| MAR-a3 | https://www.legislation.gov.uk/eur/2014/596/article/3/adopted |
| MAR-a12 | https://www.legislation.gov.uk/eur/2014/596/article/12/adopted |
| MAR-a20 | https://www.legislation.gov.uk/eur/2014/596/article/20/adopted/data.html |
| MAR-a21 | https://www.legislation.gov.uk/eur/2014/596/article/21/adopted |
| MAR-a30 | https://legislation.gov.uk/eur/2014/596/article/30/adopted |
| DR958 | https://eur-lex.europa.eu/eli/reg_del/2016/958/oj/eng |
| DR958-ch1 | https://www.legislation.gov.uk/eur/2016/958/chapter/I |
| DR958-ch2 | https://www.legislation.gov.uk/eur/2016/958/chapter/II/data.xht |
| DR958-a3 | https://www.handbook.fca.org.uk/techstandards/MAR/2016/reg_del_2016_958_oj/chapter-ii/006.html |
| FCA-958-a9 | https://www.handbook.fca.org.uk/techstandards/MAR/2016/reg_del_2016_958_oj/chapter-iii/012.html |
| MiCA | https://eur-lex.europa.eu/eli/reg/2023/1114/oj/eng |
| MiCA-91 | https://micawtf.pages.dev/mica/title-vi-prevention-and-prohibition-of-market-abuse-involving-crypto-assets-art.-86-92/article-91/ |
| MiFID2 | https://eur-lex.europa.eu/eli/dir/2014/65/oj/eng |
| DR565 | https://eur-lex.europa.eu/eli/reg_del/2017/565/oj/eng |
| AIA | https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng |
| DSA | https://eur-lex.europa.eu/eli/reg/2022/2065/oj/eng |
| CJEU-439 | https://curia.europa.eu/jcms/upload/docs/application/pdf/2021-06/cp210109fr.pdf |
| Q1737 | https://www.esma.europa.eu/publications-data/questions-answers/1737 |
| Q1738 | https://www.esma.europa.eu/publications-data/questions-answers/1738 |
| Q1740 | https://www.esma.europa.eu/publications-data/questions-answers/1740 |
| Q1741 | https://www.esma.europa.eu/publications-data/questions-answers/1741 |
| PLANET | https://www.planetcompliance.com/?p=4170 |
| ICMA | https://icmagroup.org/assets/documents/Regulatory/Secondary-markets/ICMA%20MAR%20Investment%20Recommendations%20QA%20March%202016%20210316.pdf |
| ESMA-SM21 | https://www.esma.europa.eu/sites/default/files/library/esma70-154-2780_esmas_statement_on_investment_recommendations_on_social_media.pdf |
| ESMA-SM21-PR | https://www.esma.europa.eu/press-news/esma-news/esma-addresses-investment-recommendations-made-social-media-platforms |
| ESMA-FF26 | https://esma.europa.eu/sites/default/files/2026-01/FR_France_fr_-_Finfluencers_factsheet.pdf |
| MWE26 | https://www.mondaq.com/germany/financial-services/1732616/whats-up-2026-esma-says-finfluencers |
| ESMA-ADV23 | https://www.esma.europa.eu/press-news/esma-news/esma-updates-its-guidance-definition-advice-supervisory-briefing |
| ESMA-AI24 | https://www.esma.europa.eu/sites/default/files/2024-05/ESMA35-335435667-5924__Public_Statement_on_AI_and_investment_services.pdf |
| AMF-SM21 | https://www.amf-france.org/fr/actualites-publications/communiques/communiques-de-lamf/recommandations-dinvestissement-sur-les-reseaux-sociaux-lamf-appuie-le-rappel-de-lesma |
| AMF-FF26 | https://www.amf-france.org/fr/actualites-publications/actualites/lesma-et-lamf-publient-lattention-des-finfluenceurs-des-conseils-pour-une-promotion-responsable-sur |
| AMF-SAN22 | https://www.amf-france.org/en/news-publications/news-releases/enforcement-committee-news-releases/amf-enforcement-committee-sanctions-media-company-and-its-director-making-investment-recommendations |
| AMF-SAN22-FR | https://www.amf-france.org/fr/actualites-publications/communiques/communiques-de-la-commission-des-sanctions/la-commission-des-sanctions-de-lamf-sanctionne-une-entreprise-de-presse-et-son-dirigeant-pour-des |
| MIGUET10 | https://www.lafinancepourtous.com/2012/01/26/conflit-dinteret-lamf-sanctionne-lourdement-nicolas-miguet/ |
| AMF-FORUM | https://www.lemondedudroit.fr/banque-finance/305-bourse/19997-manipulation-de-cours-et-bourse-en-ligne-sanctions-de-lamf.html |
| AMF-SURV | https://www.amf-france.org/sites/institutionnel/files/pdf/62279/fr/La_surveillance_des_marches.pdf |
| AMF-X26 | https://www.amf-france.org/fr/actualites-publications/publications/rapports-etudes-et-analyses/linfluence-des-reseaux-sociaux-sur-lactivite-des-investisseurs-particuliers-sur-les-titres-du-cac-40 |
| AMF-MICA26 | https://www.amf-france.org/fr/actualites-publications/actualites/lamf-rappelle-que-la-periode-transitoire-pour-les-psan-pour-continuer-de-fournir-des-services-sur |
| AMF-CERT | https://www.amf-france.org/fr/actualites-publications/actualites/le-certificat-de-linfluence-responsable-dans-la-finance-integre-desormais-les-evolutions-liees-au |
| AMF-PUB | https://www.amf-france.org/sites/institutionnel/files/pdf/62501/fr/Les_decisions_de_la_Commission_des_sanctions_sont-elles_publiees_.pdf |
| LOI-INFL | https://www.dalloz-actualite.fr/document/loi-n-2023-451-9-juin-2023-jo-10-juin |
| L-GBD | https://www.lagbd.org/Influenceur_sur_les_reseaux_sociaux_et_la_Loi_du_9_juin_2023 |
| DAJ-INFL | https://www.economie.gouv.fr/node/3222759 |
| SENAT-INFL | https://www.senat.fr/leg/tas22-123.html |
| ORD-2024 | https://www.vie-publique.fr/loi/296047-ordonnance-du-6-novembre-2024-modifiant-la-loi-influenceurs-de-2023 |
| ORD-2024-D | https://www.dalloz-actualite.fr/document/ord-n-2024-978-6-nov-2024-jo-7-nov |
| ORD-2024-LR | https://www.lettredesreseaux.com/influence-commerciale-assouplissement-des-obligations-dinformation-reposant-sur-linfluenceur.html |
| CMF-533 | https://french-business-law.com/french-legislation-art/article-l533-12-7-of-the-french-monetary-and-financial-code |
| CMF-465 | https://www.labase-lextenso.fr/ouvrages/droit-financier-9782275159317/b-diffusion-de-fausses-informations-9782275159317-515 |
| ACI | https://www.cabinetaci.com/information-fausse-ou-trompeuse/ |
| L1881 | https://www.eurojuris.fr/articles/les-diffamations-et-les-injures-1092.htm |
| BF22 | https://www.dalloz-actualite.fr/document/civ-1re-11-mai-2022-fs-b-n-21-16497 |
| BF23 | https://www.labase-lextenso.fr/jp-commente/cc/2023-09/22-84-763-CC-05092023-22_84763 |
| ETAT19 | https://www.revuegeneraledudroit.eu/blog/decisions/cass-crim-10-mai-2019-pourvoi-n17-84-509 |
| ETAT19b | https://www.leclubdesjuristes.com/archives-cdj/pas-daction-pour-diffamation-devant-les-tribunaux-francais-pour-les-etats-etrangers-2137/ |
| CI13 | https://www.dalloz-actualite.fr/document/civ-1re-10-avr-2013-fs-pbi-n-11-19530 |
| GSUGG13 | https://larevue.squirepattonboggs.com/google-suggere-mais-n-injurie-pas-google-n-est-pas-responsable-des-associations-realisees-par-google-suggest_a2166.html |
| DENIG | https://www.lettredesreseaux.com/?p=9997 |
| DENIG19 | https://www.actu-juridique.fr/ntic-numerique-medias-presse/denigrement-ou-diffamation-des-consequences-procedurales-distinctes/ |
| 93-3 | https://www.lemondedudroit.fr/pi-tic/299-medias/27070-responsabilite-penale-du-directeur-de-publication-en-ligne-.html |
| QPC11 | https://www.revuegeneraledudroit.eu/blog/decisions/cc-n2011-164-qpc-16-septembre-2011-m-antoine-j-responsabilite-du-producteur-dun-site-en-ligne |
| LCEN-ML | https://www.simonnetavocat.fr/mentions-legales-dun-site-internet-obligations-sanctions-et-modele/ |
| AIA-ML | https://www.morganlewis.com/blogs/sourcingatmorganlewis/2026/08/eu-ai-acts-transparency-rules-what-went-into-effect-on-2-august |
| AIA-RG | https://www.ropesgray.com/en/insights/viewpoints/2026/08/102nfqm/you-talkin-to-me-operationalising-the-eu-ai-acts-transparency-obligations |
| RIS | https://cms.law/en/int/legal-updates/eu-retail-investment-strategy-political-agreement-key-points-and-implications-for-eu-and-non-eu-firms |
| SKAD26 | https://www.skadden.com/insights/publications/2026/10/social-media-meets-financial-regulation |
| FX | https://www.thetradenews.com/mar-extension-to-spot-fx-market-needs-further-analysis-says-esma/ |
| FX2 | https://pilot.aib.ie/content/dam/aib/fxcentre/docs/aib-mifid-ii-faqs-roi.pdf |
| FCA-MAR18 | https://www.handbook.fca.org.uk/handbook/MAR/1/8.html |
| LISTING | https://www.mondaq.com/ireland/listing-rules-flotation/1546926/listing-act-part-2-market-abuse-changes |
