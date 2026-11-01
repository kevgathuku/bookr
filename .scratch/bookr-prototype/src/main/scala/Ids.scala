package bookr

// ---------------------------------------------------------------------------
// 1. Separate ID types
//    With plain integer IDs, passing a venue id where an org id is
//    expected is a runtime bug. Here it is a compile error.
//    Venues carry their org, so scope checks read it instead of trusting the caller.
// ---------------------------------------------------------------------------
final case class OrgId(value: Long) extends AnyVal
final case class VenueId(org: OrgId, value: Long) // a venue always knows its org
final case class UserId(value: Long) extends AnyVal
final case class BookingId(value: Long) extends AnyVal
final case class SessionId(value: Long) extends AnyVal
final case class MembershipId(value: Long) extends AnyVal

def venueTimezone(venue: VenueId): String = "Europe/Madrid" // stub

// venueTimezone(OrgId(1))        // does not compile: OrgId is not a VenueId
