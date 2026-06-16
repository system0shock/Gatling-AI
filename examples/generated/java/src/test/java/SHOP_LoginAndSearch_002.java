import io.gatling.javaapi.core.ChainBuilder;
import io.gatling.javaapi.core.ScenarioBuilder;
import io.gatling.javaapi.core.Simulation;
import io.gatling.javaapi.http.HttpProtocolBuilder;
import java.time.Duration;

import static io.gatling.javaapi.core.CoreDsl.*;
import static io.gatling.javaapi.http.HttpDsl.*;

public class SHOP_LoginAndSearch_002 extends Simulation {

  private static String requiredEnv(String name) {
    String value = System.getenv(name);
    if (value == null || value.isBlank()) {
      throw new IllegalStateException("Missing required environment variable: " + name);
    }
    return value;
  }

  private final HttpProtocolBuilder httpProtocol = http.baseUrl(requiredEnv("BASE_URL"));

  private final ChainBuilder openLogin =
    exec(
          http("01 auth.open-login - Open login page")
            .get("/login")
            .check(status().is(200))
            .check(css("input[name=csrf]").saveAs("csrf"))
    );

  private final ChainBuilder submitLogin =
    exec(
          http("02 auth.login - Submit credentials")
            .post("/login")
            .disableFollowRedirect()
            .header("Content-Type", "application/x-www-form-urlencoded")
            .body(StringBody("user=#{username}&pass=#{password}&csrf=#{csrf}"))
            .check(status().is(302))
    );

  private final ScenarioBuilder scenario = scenario("Login and search product")
    .feed(csv("users.csv").circular())
    .group("01 auth.open-login - Open login page").on(openLogin)
    .group("02 auth.login - Submit credentials").on(submitLogin);

  {
    setUp(
      scenario.injectClosed(
        rampConcurrentUsers(0).to(10).during(Duration.ofSeconds(30)),
        constantConcurrentUsers(10).during(Duration.ofSeconds(120))
      )
    ).protocols(httpProtocol)
      .assertions(
        global().responseTime().percentile(95.0).lt(800)
      );
  }
}
