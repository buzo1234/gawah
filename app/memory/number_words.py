"""Hindi number words, one to ninety-nine, as they are spelt in Roman Hinglish and in
Devanagari (with the spellings transcription gives), plus the English ones people mix in.
Data only: normalise.py reads them."""

ROMAN = """
1 ek
2 do
3 teen tin
4 char chaar chaar
5 paanch panch paach panj paanc
6 chhe chhah che chah chheh chhai chha chhey chhay
7 saat sat
8 aath ath aanth
9 nau nao
10 das dus
11 gyarah gyara gyaarah gyaara igyarah egyarah
12 barah bara baarah baara
13 terah tera terha
14 chaudah chauda chaudha choudah chouda chodah
15 pandrah pandra pandhrah pandhra pandara
16 solah sola
17 satrah satra sattrah sattra
18 atharah athara attharah atthara athrah athaara
19 unnees unnis unees unis
20 bees bis
21 ikkees ikkis ekkis ekkees
22 baees bais baais baaees baiis baayees
23 teis teish teyis teiis teyees tayees teees
24 chaubees chaubis chobis choubis chaubiis
25 pachchees pachees pachis pacchis pachchis pachhees pachhis
26 chhabbees chhabbis chabbis chhabis chabbees
27 sattaees sattais sataees satais sattaais
28 atthaees atthais athais athaees atthaais athaais adthais
29 untees untis unatees unatis
30 tees tis
31 ikattees iktees ikatees ikattis iktis ikatis
32 battees batees battis batis
33 taintees tentis taintis tetis taitees taitis tentees
34 chautees chauntees chautis chauntis chontis chountis
35 paintees paintis pentis paitees paitis pentees
36 chhattees chhattis chattis chhatees chatis chattees
37 saintees saintis sentis saitees saitis sentees
38 adtees adhtees artees arthees adtis adhtis artis arthis aratees aratis adatees athtees athtis adtiis
39 untaalees untalis untalees unchalis unchalees untaalis
40 chaalees chalees chalis chaalis
41 iktaalees iktalis iktalees iktaalis ekchalis
42 bayaalees byalis bayalis biyalis bayaalis byaalis bayalees
43 taintaalees taintalis tentalis taintalees tetalis
44 chavaalees chawalis chavalis chauvalis chaowalis chawaalis chavalees chauvalees
45 paintaalees paintalis pentalis paintalees
46 chhiyaalees chhiyalis chiyalis chhiyalees chhiyaalis
47 saintaalees saintalis sentalis saintalees
48 adtaalees adtalis artalis adtalees artalees arhtalis adhtalis
49 unchaas unchas unanchas
50 pachaas pachas
51 ikyaavan ikyavan ekyavan ikyawan ekyawan
52 baavan bavan baawan bawan
53 tirepan tirpan tirapan tiraipan
54 chauvan chauwan chouwan chauvaan
55 pachpan pachapan
56 chhappan chappan chhapan
57 sattaavan sattavan satavan sattawan satawan
58 atthaavan atthavan athavan atthawan athawan
59 unsath unsaath unasath
60 saath sath
61 iksath eksath iksaath
62 baasath basath baasaath
63 tirsath tiresath tirsaath
64 chaunsath chausath chausaath chonsath
65 painsath painsaath pensath
66 chhiyaasath chhiyasath chiyasath chhiyaasaath
67 sadsath sadsaath sarsath
68 adsath adsaath arsath arsaath
69 unhattar unattar
70 sattar
71 ikhattar ikattar
72 bahattar bahatar
73 tihattar tihatar
74 chauhattar chauhatar
75 pachhattar pachattar pachhatar
76 chhihattar chihattar
77 satattar sathattar sathatar satahattar
78 athhattar athattar athhatar
79 unaasi unasi unyasi
80 assi asi
81 ikyaasi ikyasi ekyasi
82 bayaasi bayasi biyasi
83 tiraasi tirasi
84 chauraasi chaurasi
85 pachaasi pachasi
86 chhiyaasi chhiyasi chiyasi
87 sataasi satasi sattasi
88 athaasi athasi atthasi
89 navaasi navasi nawasi
90 nabbe nabe
91 ikyaanave ikyanve ikyaanve ekyanve
92 baanave baanve banve
93 tiraanave tiranve tiraanve
94 chauraanave chauranve chauraanve
95 pachaanave pachanve pachaanve
96 chhiyaanave chhiyanve chiyanve chhiyaanve
97 sattaanave sattanve sattaanve
98 atthaanave atthanve athanve atthaanve
99 ninyaanave ninyanve ninyaanve ninanve
"""

DEVANAGARI = """
1 एक
2 दो
3 तीन
4 चार
5 पांच पाँच पाच
6 छह छः छे छै छेह
7 सात
8 आठ
9 नौ
10 दस
11 ग्यारह ग्यारा
12 बारह बारा
13 तेरह
14 चौदह
15 पंद्रह पन्द्रह पंदरह
16 सोलह
17 सत्रह सतरह
18 अठारह अट्ठारह
19 उन्नीस उनीस
20 बीस
21 इक्कीस
22 बाईस बाइस
23 तेईस तेइस
24 चौबीस
25 पच्चीस पचीस
26 छब्बीस
27 सत्ताईस सत्ताइस
28 अट्ठाईस अठाईस अट्ठाइस
29 उनतीस उन्तीस
30 तीस
31 इकतीस इकत्तीस
32 बत्तीस
33 तैंतीस तेंतीस तैतीस
34 चौंतीस चौतीस
35 पैंतीस पैतीस
36 छत्तीस
37 सैंतीस सैतीस
38 अड़तीस अडतीस अठतीस
39 उनतालीस उन्तालीस
40 चालीस
41 इकतालीस
42 बयालीस बियालीस
43 तैंतालीस तेंतालीस
44 चवालीस चौवालीस चव्वालीस
45 पैंतालीस
46 छियालीस
47 सैंतालीस
48 अड़तालीस
49 उनचास
50 पचास
51 इक्यावन
52 बावन
53 तिरेपन तिरपन
54 चौवन चव्वन
55 पचपन
56 छप्पन
57 सत्तावन
58 अट्ठावन अठावन
59 उनसठ
60 साठ
61 इकसठ
62 बासठ
63 तिरेसठ तिरसठ
64 चौंसठ चौसठ
65 पैंसठ
66 छियासठ
67 सड़सठ सरसठ
68 अड़सठ
69 उनहत्तर
70 सत्तर
71 इकहत्तर
72 बहत्तर
73 तिहत्तर
74 चौहत्तर
75 पचहत्तर
76 छिहत्तर
77 सतहत्तर
78 अठहत्तर
79 उन्यासी उनासी
80 अस्सी
81 इक्यासी
82 बयासी
83 तिरासी
84 चौरासी
85 पचासी
86 छियासी
87 सत्तासी
88 अट्ठासी
89 नवासी
90 नब्बे
91 इक्यानबे इक्यानवे
92 बानबे बानवे
93 तिरानबे तिरानवे
94 चौरानबे चौरानवे
95 पचानबे पंचानबे पचानवे
96 छियानबे छियानवे
97 सत्तानबे सत्तानवे
98 अट्ठानबे अट्ठानवे
99 निन्यानबे निन्यानवे
"""

# English, as said and as transcribed into Devanagari. Tens can take a unit after them ("twenty five").
ENGLISH = """
1 one
2 two
3 three थ्री
4 four फोर
5 five फाइव फाईव
6 six सिक्स
7 seven सेवन
8 eight एट
9 nine नाइन
10 ten टेन
11 eleven इलेवन
12 twelve ट्वेल्व
13 thirteen थर्टीन
14 fourteen फोर्टीन
15 fifteen फिफ्टीन
16 sixteen सिक्सटीन
17 seventeen सेवनटीन
18 eighteen एटीन
19 nineteen नाइनटीन
20 twenty ट्वेंटी ट्वेन्टी
30 thirty थर्टी
40 forty फोर्टी
50 fifty फिफ्टी
60 sixty सिक्सटी
70 seventy सेवेंटी सेवंटी
80 eighty एटी
90 ninety नाइंटी
"""


def table(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in text.strip().splitlines():
        value, *spellings = row.split()
        for s in spellings:
            out[s] = int(value)
    return out
