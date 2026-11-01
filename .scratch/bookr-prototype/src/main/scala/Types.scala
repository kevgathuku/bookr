package bookr

import java.time.Duration

// ---------------------------------------------------------------------------
// 2. A value that can only be built valid (smart constructor)
//    A raw duration admits negatives unless every use site checks, while
//    the baseline's zero window must stay buildable. Here negatives are
//    refused and zero passes — the bound is >= 0, matching the field.
// ---------------------------------------------------------------------------
object Types:
  opaque type CancelWindow = Duration

  object CancelWindow:
    def of(d: Duration): Either[String, CancelWindow] =
      if d.isNegative then Left("cancel window must not be negative")
      else Right(d)

    def zero: CancelWindow = Duration.ZERO

  extension (w: CancelWindow) def duration: Duration = w

  opaque type CreditBalance = Int
  object CreditBalance:
    def of(n: Int): Either[String, CreditBalance] =
      if n < 0 then Left("credits must not be negative") else Right(n)
  extension (b: CreditBalance)
    def remaining: Int = b
    def add(n: Int): CreditBalance = b + n
    def spend(n: Int): Either[String, CreditBalance] =
      if n > b then Left("insufficient credits") else Right(b - n)

  opaque type Money = Long
  object Money:
    def of(cents: Long): Either[String, Money] =
      if cents < 0 then Left("money must not be negative") else Right(cents)
  extension (m: Money) def cents: Long = m

  opaque type Reason = String
  object Reason:
    def of(s: String): Either[String, Reason] =
      if s.trim.isEmpty then Left("reason is required") else Right(s)
  extension (r: Reason) def text: String = r
