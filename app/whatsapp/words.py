"""What Gawah says on WhatsApp about deals and calls. Short, plain Hinglish in Roman
script. Gawah never gives an opinion on a deal, so none of these do. The lines about
records are in app/records/words.py."""

from app.contracts import Person

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


def call_link(url: str) -> str:
    return f"Namaste! Gawah aapki deal ka gawah rahega. Call ke liye yeh link kholiye: {url}"


def call_link_for_other(requester: Person, url: str) -> str:
    asked_by = f"{requester.name} ji ({requester.phone})" if requester.name else requester.phone
    return (
        f"Namaste! {asked_by} aapke saath kaam ki deal pakki karna chahte hain. "
        f"Gawah is call ka gawah rahega. Call ke liye yeh link kholiye: {url}"
    )


def callback_link(url: str) -> str:
    return f"Gawah aapse akele mein deal ki sharten confirm karna chahta hai. Yeh link kholiye: {url}"


def follow_up(url: str) -> str:
    return f"Aapka jawab nahi aaya. Gawah aapse baat karke confirm karna chahta hai. Yeh link kholiye: {url}"
