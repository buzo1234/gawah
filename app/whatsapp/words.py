"""What Gawah says on WhatsApp about deals and calls. Short, plain Hinglish in Roman
script. Gawah never gives an opinion on a deal, so none of these do. The lines about
records are in app/records/words.py."""

from app.contracts import Person
from app.records.words import who

HELP_NO_DEAL = (
    "Namaste, main Gawah hoon. Deal shuru karne ke liye doosre vyakti ka mobile number bhejiye."
)
HELP = (
    "Yeh samajh nahi aaya. Payment ka screenshot bhejiye, ya likhiye jaise '2000 cash diya' "
    "ya 'kaam poora ho gaya'. Nayi deal ke liye doosre vyakti ka mobile number bhejiye."
)
OWN_NUMBER = "Yeh aapka apna number hai. Doosre vyakti ka mobile number bhejiye."
MANY_NUMBERS = "Ek se zyada number mile. Sirf doosre vyakti ka ek mobile number bhejiye."
READ_FAILED = "Abhi yeh padh nahi paaya. Thodi der mein dobara bhejiye."
CONTRACT = "Aapki deal ka contract taiyaar hai. Neeche PDF aur awaaz mein summary hai."
CONTRACT_PDF_ONLY = "Aapki deal ka contract taiyaar hai. Neeche PDF hai."
CONTRACT_VOICE_ONLY = "Aapki deal ka contract taiyaar hai. Neeche awaaz mein summary hai. PDF abhi nahi bhej paaye."
CONTRACT_NO_FILE = "Aapki deal ka contract taiyaar hai, par uski file abhi nahi bhej paaye."


def contract(pdf: bool, voice: bool) -> str:
    """The line before the files: it names only what is really attached."""
    return {(True, True): CONTRACT, (True, False): CONTRACT_PDF_ONLY, (False, True): CONTRACT_VOICE_ONLY}.get(
        (pdf, voice), CONTRACT_NO_FILE
    )


def call_link(url: str) -> str:
    return f"Namaste! Gawah aapki deal ka gawah rahega. Call ke liye yeh link kholiye: {url}"


def call_link_for_other(requester: Person, url: str) -> str:
    asked_by = f"{requester.name} ji ({requester.phone})" if requester.name else requester.phone
    return (
        f"Namaste! {asked_by} aapke saath kaam ki deal pakki karna chahte hain. "
        f"Gawah is call ka gawah rahega. Call ke liye yeh link kholiye: {url}"
    )


def call_opened(opener: Person, url: str) -> str:
    return f"{who(opener)} aapse deal par phir se baat karna chahte hain. Call ke liye yeh link kholiye: {url}"


def callback_link(url: str) -> str:
    return f"Gawah aapse akele mein deal ki sharten confirm karna chahta hai. Yeh link kholiye: {url}"


def follow_up(url: str) -> str:
    return f"Aapka jawab nahi aaya. Gawah aapse baat karke confirm karna chahta hai. Yeh link kholiye: {url}"
