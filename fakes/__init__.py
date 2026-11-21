"""Stand-ins for the call and for WhatsApp, so a stream can be built and tested with
no other stream and no outside service present."""

from app.contracts import Person, Role

SUNITA = Person(role=Role.HIRER, name="Sunita", phone="+910000000001")
RAMESH = Person(role=Role.WORKER, name="Ramesh", phone="+910000000002")
