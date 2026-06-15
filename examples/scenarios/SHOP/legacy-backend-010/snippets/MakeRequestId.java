// Translated from migration/jsr223/0692b2c52e4c.groovy
// Original: def rid = UUID.randomUUID().toString(); vars.put("requestId", rid)
// Gatling Session is immutable — return the updated session.
import io.gatling.javaapi.core.Session;

public final class MakeRequestId {

    private MakeRequestId() {
    }

    public static Session apply(Session session) {
        return session.set("requestId", java.util.UUID.randomUUID().toString());
    }
}
