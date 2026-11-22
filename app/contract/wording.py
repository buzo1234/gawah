"""The fixed words of the agreement, in Hindi and English. Nothing here comes from a call."""

from app.contract.terms import Bi
from app.contracts import ItemKey, Role

TITLE = Bi("काम का अनुबंध", "Work Agreement")
SUBTITLE = Bi(
    "रिकॉर्ड की गई फ़ोन कॉल पर बोलकर हुए समझौते का लिखित रिकॉर्ड",
    "Written record of an agreement made by voice on a recorded call",
)
PARTIES = {Role.HIRER: Bi("पहला पक्ष", "First party"), Role.WORKER: Bi("दूसरा पक्ष", "Second party")}
ROLES = {Role.HIRER: Bi("काम देने वाले", "the hirer"), Role.WORKER: Bi("काम करने वाले", "the worker")}
LEAD = Bi("दोनों पक्षों ने कॉल पर ये बातें तय कीं।", "The two parties agreed the following on the call.")
CLAUSES = {
    ItemKey.WORK: Bi("काम", "The work"),
    ItemKey.AMOUNT: Bi("कीमत और उसमें क्या शामिल है", "The price and what it covers"),
    ItemKey.DATES: Bi("काम की तारीखें", "The dates"),
    ItemKey.LATE_OR_UNFINISHED: Bi("देर हुई या काम अधूरा रहा तो", "If the work is late or left unfinished"),
}
PAYMENT_CLAUSE = Bi("भुगतान कब और कैसे", "Payment schedule")
PAYMENTS = {ItemKey.ADVANCE: Bi("एडवांस", "Advance"), ItemKey.BALANCE: Bi("बाकी पैसा", "Balance")}
THE_REST = Bi("बाकी रकम", "The rest")
AS_STATED = Bi("जैसा आगे लिखा है", "As stated")
OPEN_CLAUSE = Bi("जो बातें तय नहीं हुईं", "What was not agreed")
NOT_AGREED = Bi("यह बात कॉल पर तय नहीं हुई।", "This was not agreed on the call.")
OPEN_POINTS = {
    ItemKey.WORK: Bi("काम क्या है", "what the work is"),
    ItemKey.AMOUNT: Bi("कीमत और उसमें क्या शामिल है", "the price and what it covers"),
    ItemKey.ADVANCE: Bi("एडवांस कितना और कब", "the advance, how much and when"),
    ItemKey.BALANCE: Bi("बाकी पैसा कब और किस बात पर मिलेगा", "when the balance is paid and against what"),
    ItemKey.DATES: Bi("काम कब शुरू और कब पूरा होगा", "the start and finish dates"),
    ItemKey.LATE_OR_UNFINISHED: Bi("देर होने या काम अधूरा रहने पर क्या होगा", "what happens if the work is late or left unfinished"),
}
ALL_AGREED = Bi(
    "गवाह छह बातें पूछता है: काम, कीमत, एडवांस, बाकी पैसा, तारीखें, और देर होने या काम अधूरा रहने पर क्या होगा। "
    "ये सभी छह बातें कॉल पर तय हुईं।",
    "Gawah checks six points: the work, the price, the advance, the balance, the dates, and what happens "
    "if the work is late or left unfinished. All six were agreed on the call.",
)
CONFIRMED = Bi("गवाह के साथ अलग कॉल पर बोलकर पुष्टि की", "Confirmed by voice on a separate call with Gawah")
ON_THE_CALL = Bi("गवाह के सामने कॉल पर बोलकर तय किया", "Agreed by voice on the call, with Gawah as witness")  # call-backs off
WITNESS = Bi(
    "गवाह (Gawah) एक AI गवाह है। वह इस कॉल पर मौजूद था, और दोनों लोगों के रिकॉर्डिंग के लिए हाँ कहने के बाद उसने कॉल रिकॉर्ड की।",
    "Gawah is an AI witness. It was on the call, and recorded it after both people agreed to the recording.",
)
FINGERPRINT = Bi(
    "रिकॉर्डिंग की पहचान (SHA-256)। रिकॉर्डिंग ज़रा भी बदले तो ये अक्षर बदल जाते हैं।",
    "Recording fingerprint (SHA-256). If a recording is changed at all, these characters change.",
)
VOICES = {Role.HIRER: Bi("पहले पक्ष की आवाज़", "First party's audio"), Role.WORKER: Bi("दूसरे पक्ष की आवाज़", "Second party's audio")}
IS = Bi(
    "यह दस्तावेज़ बोलकर हुए समझौते का लिखित रिकॉर्ड है, जिसकी दोनों लोगों ने अलग-अलग पुष्टि की है।",
    "This document is a written record of a spoken agreement, confirmed separately by both people.",
)
IS_NOT = Bi(
    "इसे किसी वकील ने तैयार नहीं किया है और यह स्टाम्प पेपर पर नहीं है।",
    "It was not drafted by a lawyer and is not on stamp paper.",
)
IF_YOU_DISAGREE = Bi(
    "अगर बाद में किसी बात पर असहमति हो, तो दोनों में से कोई भी गवाह से उस बात की रिकॉर्डिंग माँग सकता है।",
    "If either person disagrees later, they can ask Gawah for the recording of any term.",
)
ALSO_AGREED = Bi("और जो तय हुआ", "Also agreed")
CHANGED = Bi("बदला गया", "changed")
CHANGES = Bi("बदलाव", "Changes")
CHANGES_LEAD = Bi(
    "ये बातें पहली बार तय होने के बाद बदलीं, इसी क्रम में। हर बदलाव दोनों लोगों ने कॉल पर बोलकर पक्का किया।",
    "These terms were changed after they were first agreed, in this order. Each change was confirmed "
    "by both people by voice on a call.",
)
BOTH_CONFIRMED = Bi("दोनों ने कॉल पर बोलकर पक्का किया", "Confirmed by both by voice on the call")
BEFORE, NOW = Bi("पहले", "Before"), Bi("अब", "Now")
CALLS = Bi("कॉल", "Calls")
CHAIN = Bi("गवाह की कड़ी", "Witness chain")
CHAIN_MEANS = Bi(
    "गवाह ने जो भी बात दर्ज की, वह अपने से पहले वाली बात से एक पहचान (SHA-256) से जुड़ी है। "
    "दर्ज की गई किसी भी बात को बाद में बदला गया तो यह कड़ी टूट जाएगी और आख़िरी पहचान मेल नहीं खाएगी।",
    "Every fact Gawah recorded is linked to the one before it by a fingerprint (SHA-256). "
    "Any later change to a recorded fact would break this chain, and the last fingerprint would no longer match.",
)
