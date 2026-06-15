// Translated from migration/jsr223/0692b2c52e4c.groovy
// Original: def rid = UUID.randomUUID().toString(); vars.put("requestId", rid)
// Gatling Session is immutable — return the updated session.
session -> session.set("requestId", java.util.UUID.randomUUID().toString())
