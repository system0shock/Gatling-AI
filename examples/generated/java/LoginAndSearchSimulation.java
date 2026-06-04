import io.gatling.javaapi.core.ScenarioBuilder;
import io.gatling.javaapi.core.Simulation;
import io.gatling.javaapi.http.HttpProtocolBuilder;
import java.time.Duration;

import static io.gatling.javaapi.core.CoreDsl.*;
import static io.gatling.javaapi.http.HttpDsl.*;

public class LoginAndSearchSimulation extends Simulation {

  private static String requiredEnv(String name) {
    String value = System.getenv(name);
    if (value == null || value.isBlank()) {
      throw new IllegalStateException("Missing required environment variable: " + name);
    }
    return value;
  }

  private final HttpProtocolBuilder httpProtocol = http.baseUrl(requiredEnv("BASE_URL"));

  private final ScenarioBuilder scenario = scenario("Login and search product")
    .feed(csv("users.csv").circular())
    .group("01 auth.open-login - Open login page").on(
      exec(
          http("01 auth.open-login - Open login page")
            .get("/login")
            .check(status().is(200))
            .check(css("input[name=csrf]").saveAs("csrf"))
      )
    )
    .group("02 auth.login - Submit credentials").on(
      exec(
          http("02 auth.login - Submit credentials")
            .post("/login")
            .header("Content-Type", "application/x-www-form-urlencoded")
            .body(StringBody("user=${username}&pass=${password}&csrf=${csrf}"))
            .check(status().is(302))
      )
    );

  {
    setUp(
      scenario.injectClosed(
        rampConcurrentUsers(0).to(10).during(Duration.ofSeconds(30)),
        constantConcurrentUsers(10).during(Duration.ofSeconds(120))
      )
    ).protocols(httpProtocol);
  }
}
