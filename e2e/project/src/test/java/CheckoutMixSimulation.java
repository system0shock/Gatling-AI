import io.gatling.javaapi.core.ScenarioBuilder;
import io.gatling.javaapi.core.Simulation;
import io.gatling.javaapi.http.HttpProtocolBuilder;
import java.time.Duration;

import static io.gatling.javaapi.core.CoreDsl.*;
import static io.gatling.javaapi.http.HttpDsl.*;

public class CheckoutMixSimulation extends Simulation {

  private static String requiredEnv(String name) {
    String value = System.getenv(name);
    if (value == null || value.isBlank()) {
      throw new IllegalStateException("Missing required environment variable: " + name);
    }
    return value;
  }

  private final HttpProtocolBuilder httpProtocol = http.baseUrl(requiredEnv("BASE_URL"));

  private final ScenarioBuilder checkout = scenario("checkout")
    .feed(csv("search-terms.csv").circular())
    .group("01 catalog.list - Open product list").on(
      exec(
          http("01 catalog.list - Open product list")
            .get("/products")
            .check(status().is(200))
            .check(jsonPath("$.items[0].id").saveAs("productId"))
      )
    ).pause(Duration.ofSeconds(1))
    .group("02 catalog.price - Get product price").on(
      exec(
          http("02 catalog.price - Get product price")
            .post("/graphql")
            .header("Content-Type", "application/json")
            .body(StringBody("{\"query\":\"query Price($id: ID!) {\\n  price(id: $id)\\n}\\n\",\"variables\":{\"id\":\"#{productId}\"}}"))
            .check(status().is(200))
      )
    )
    .group("03 checkout.submit - Submit checkout").on(
      exec(
          http("03 checkout.submit - Submit checkout")
            .post("/checkout")
            .header("Content-Type", "application/json")
            .body(StringBody("{\"productId\": \"#{productId}\"}"))
            .check(status().is(200))
      )
    );

  private final ScenarioBuilder search = scenario("search")
    .feed(csv("search-terms.csv").circular())
    .group("04 catalog.search - Search catalog").on(
      exec(
          http("04 catalog.search - Search catalog")
            .get("/search?q=#{term}")
            .check(status().is(200))
      )
    );

  {
    setUp(
      checkout.injectClosed(
        incrementConcurrentUsers(5).times(2).eachLevelLasting(Duration.ofSeconds(30)).startingFrom(5)
      ),
      search.injectOpen(
        constantUsersPerSec(2).during(Duration.ofSeconds(60))
      )
    ).protocols(httpProtocol)
      .assertions(
        global().responseTime().percentile(95.0).lt(800),
        global().successfulRequests().percent().gt(99.0)
      );
  }
}
