package bookr

// ---------------------------------------------------------------------------
// 7. Role scope instead of a nullable venue
//    A nullable venue where None means "org-wide" by convention only.
// ---------------------------------------------------------------------------
enum Scope:
  case OrgWide(org: OrgId)
  case AtVenue(venue: VenueId)

enum Role:
  case Owner, Manager, Frontdesk, Teacher, Member

// Mirrors organizations/capabilities.py: desk operation, staff management,
// waiver, door operation, free entry. Policy edits happen through the admin
// behind staff gates — there is no named capability for them, so neither
// is there one here.
enum Capability:
  case OperateDesk, ManageStaff, WaivePenalty, OperateDoor, EnterFree

final case class RoleAssignment(user: UserId, role: Role, scope: Scope)

// The venue carries its org, so "org-wide" is checkable: the scope's org
// must equal the venue's own org. A venue from another org never matches.
def appliesAt(scope: Scope, venue: VenueId): Boolean = scope match
  case Scope.OrgWide(o) => o == venue.org
  case Scope.AtVenue(v) => v == venue

// This match has no catch-all case. If you add a Role (say, Assistant) and
// forget it here, the compiler warns about a non-exhaustive match. Make
// warnings fatal (-Xfatal-warnings in Scala 3.3) and it becomes a build
// failure. With stringly-typed roles, a forgotten role silently gets no
// capabilities.
def capabilities(role: Role): Set[Capability] = role match
  case Role.Owner =>
    Set(Capability.OperateDesk, Capability.ManageStaff, Capability.WaivePenalty,
        Capability.OperateDoor, Capability.EnterFree)
  case Role.Manager =>
    Set(Capability.OperateDesk, Capability.ManageStaff, Capability.WaivePenalty,
        Capability.OperateDoor, Capability.EnterFree)
  case Role.Frontdesk =>
    Set(Capability.OperateDesk, Capability.WaivePenalty,
        Capability.OperateDoor, Capability.EnterFree)
  case Role.Teacher => Set(Capability.OperateDoor, Capability.EnterFree)
  case Role.Member  => Set.empty

def can(assignments: List[RoleAssignment], user: UserId, venue: VenueId,
        cap: Capability): Boolean =
  assignments.exists { a =>
    a.user == user && appliesAt(a.scope, venue) && capabilities(a.role).contains(cap)
  }

// Entry privilege vs operator authority: identical today, separate so they
// can diverge without touching gates.
def canOperateDoor(assignments: List[RoleAssignment], user: UserId,
                   venue: VenueId): Boolean =
  can(assignments, user, venue, Capability.OperateDoor)

def isDutyStaff(assignments: List[RoleAssignment], user: UserId,
                venue: VenueId): Boolean =
  can(assignments, user, venue, Capability.EnterFree)

// ---------------------------------------------------------------------------
// 8. Authority as a value, not a prayer.
//    Waivers demand a Grant, and the only way to mint one is authorize,
//    which runs the capability check. The grant carries the scope it was
//    checked against, and decide re-verifies it: a grant is proof of a
//    check, not a substitute for one. (Residual TOCTOU — rights revoked
//    between authorize and decide — is why the write path re-checks inside
//    its transaction; types move the check earlier, they don't remove it.)
// ---------------------------------------------------------------------------
object WaiverAuthority:
  opaque type Grant = (UserId, Scope)

  def authorize(user: UserId, assignments: List[RoleAssignment],
                venue: VenueId): Option[Grant] =
    if can(assignments, user, venue, Capability.WaivePenalty) then
      Some((user, Scope.AtVenue(venue)))
    else None

  extension (g: Grant)
    def user: UserId = g._1
    def scope: Scope = g._2
