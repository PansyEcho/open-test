# Design

Use JavaParser's existing resolved method declarations. Exact resolution remains authoritative. After it fails, the receiver must be SOFContext or its subtype, and every same-name method that can accept the argument count must be declared by SOFContext. A non-SOF declaration, missing candidate or unresolved hierarchy keeps the existing `sof_event_dispatch_unresolved` warning instead of guessing a dispatch edge. Fixed arity and varargs both participate; incompatible argument counts do not block a valid SOF candidate. Explicit and implicit receivers share this decision.

The existing warning boundary records one bounded reason. No new logging context or runtime mechanism is needed in the pure analyzer helper.
