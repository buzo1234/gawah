"""CALLBACKS_ENABLED=false: no call-back after a deal call. What both agreed on the call
counts as confirmed by both, so memory, the clerk and the Sentinel work as after two call-backs.

At the end of each deal call, for each person and each term memory has agreed (or confirmed)
that this person has not confirmed, the same per-term terms.confirmed a call-back would send.
A term not agreed stays as it is, and a change both confirmed through Gawah on the call is
already confirmed by both, so it is skipped. app/whatsapp wires this where the Sentinel is
built, and sends no call-back links; the call-back page says there is nothing to confirm."""

from app.bus import Bus
from app.config import Settings
from app.contracts import (
    AgentNote, CallEnded, CallKind, CrewAgent, FactStatus, ItemKey, MemoryQueries, Role, TermsConfirmed,
)

SAID = "agreed on the call"


class CallbackSettings(Settings):
    callbacks_enabled: bool = True


def callbacks_enabled(settings: Settings | None) -> bool:
    if isinstance(settings, CallbackSettings):
        return settings.callbacks_enabled
    return CallbackSettings().callbacks_enabled  # from the shell, the secret or .env; the shared settings stay as given


class NoCallbacks:
    def __init__(self, bus: Bus, memory: MemoryQueries) -> None:
        self.bus, self.memory = bus, memory

    def subscribe(self) -> None:
        self.bus.subscribe(CallEnded, self.on_call_ended)

    async def on_call_ended(self, event: CallEnded) -> None:
        if event.kind is not CallKind.DEAL:
            return
        settle = getattr(self.memory, "settle", None)  # not in MemoryQueries; the real memory has it
        if settle:
            await settle()  # the call's last lines read first
        done = []
        for item in ItemKey:
            term = (await self.memory.get_term(event.deal_id, item)).current
            if term is None or term.status not in (FactStatus.AGREED, FactStatus.CONFIRMED):
                continue
            for role in Role:
                if role not in term.confirmed_by:
                    self.bus.publish(TermsConfirmed(
                        deal_id=event.deal_id, person=role, item=item, value=term.value or term.text, said=SAID,
                    ))
                    done.append(f"{item.value} for the {role.value}")
        self.bus.publish(AgentNote(
            deal_id=event.deal_id, agent=CrewAgent.SENTINEL,
            text=f"call {event.call_no}: call-backs off, "
                 + (f"agreed on the call counts as confirmed: {', '.join(done)}" if done else "nothing new to confirm"),
        ))
