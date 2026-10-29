# Bookr

How venues sell and fill classes, appointments, and door access on one platform.

## Language

**Organization**:
The business running venues on the platform.
_Avoid_: tenant, account, company

**Venue**:
One location where classes and appointments happen.
_Avoid_: gym, club

**Venue policy**:
The booking rules in force at a venue — cancel windows, buffers, holds.
_Avoid_: settings, config

**Membership**:
A person's role at an organization, optionally pinned to one venue.
_Avoid_: account, enrollment

**Spanning membership**:
A membership covering every venue of its organization.
_Avoid_: global membership

**Member**:
A person entitled to book, holding a membership.
_Avoid_: customer, client

**Booking**:
A member's claim on one class seat or appointment.
_Avoid_: reservation, order

**Waitlist**:
The first-come queue for a full class.
_Avoid_: standby list

**Hold**:
The window a promoted waitlister has to claim the seat.
_Avoid_: timeout

**Late cancel**:
A cancellation inside the venue's cutoff window, forfeiting the credit.
_Avoid_: late drop

**No-show**:
A booking neither attended nor cancelled.
_Avoid_: ghost booking

**Strike**:
A late cancel or no-show counted toward throttling repeat offenders.

**Pass**:
A bundle of class credits, possibly unlimited.
_Avoid_: package, subscription

**Credit ledger**:
The authoritative record of credit movements.
_Avoid_: balance, wallet

**Substitution**:
One teacher replacing another for a class, with history kept.
_Avoid_: swap, cover

**Aggregator**:
A third-party platform reselling a venue's classes.
_Avoid_: partner, reseller

**Allotment**:
The seats per class reserved for one aggregator.
_Avoid_: quota

**Access event**:
One recorded door grant-or-deny decision.
_Avoid_: log entry
